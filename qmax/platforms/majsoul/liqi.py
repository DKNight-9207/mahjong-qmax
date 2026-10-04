# 雀魂協定（liqi）：從 liqi.desc 載入 protobuf 定義，解碼 WebSocket 訊框。
# 改寫自 MajsoulMax 的 liqi_new.py。
import base64
from functools import cache
from pathlib import Path
from struct import unpack

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf.json_format import MessageToDict

from qmax.platforms.base import Decoder, Message
from qmax.platforms.majsoul.messages import ACTION_PROTOTYPE

LIQI_DESC = Path(__file__).with_name("liqi.desc")

NOTIFY, REQUEST, RESPONSE = 1, 2, 3
TYPE_NAMES = {NOTIFY: "Notify", REQUEST: "Req", RESPONSE: "Res"}


class Schema:
    def __init__(self, desc: bytes):
        files = descriptor_pb2.FileDescriptorSet()
        files.ParseFromString(desc)
        self._pool = descriptor_pool.DescriptorPool()
        for file in files.file:
            self._pool.Add(file)
        self._factory = message_factory.MessageFactory(self._pool)
        # ".lq.FastTest.authGame" -> ("ReqAuthGame", "ResAuthGame")
        self.rpc: dict[str, tuple[str, str]] = {
            f".{file.package}.{service.name}.{method.name}": (
                method.input_type.rsplit(".", 1)[-1],
                method.output_type.rsplit(".", 1)[-1],
            )
            for file in files.file
            for service in file.service
            for method in service.method
        }

    def parse(self, type_name: str, data: bytes):
        """type_name 不含套件名，例如 "ActionDiscardTile"。"""
        cls = self._factory.GetPrototype(self._pool.FindMessageTypeByName(f"lq.{type_name}"))
        return cls.FromString(data)

    def unwrap(self, data: bytes) -> tuple[str, bytes]:
        """lq.Wrapper：(方法或訊息名稱, 內層資料)。"""
        wrapper = self.parse("Wrapper", data)
        return wrapper.name, wrapper.data


@cache
def schema() -> Schema:
    return Schema(LIQI_DESC.read_bytes())


def to_dict(proto_obj) -> dict:
    return MessageToDict(proto_obj, preserving_proto_field_name=True, including_default_value_fields=True)


class LiqiDecoder(Decoder):
    """訊框：1 byte 類型 + （Req/Res 才有）2 byte 編號 + lq.Wrapper。

    Res 不帶方法名稱，要靠同一條連線上先前 Req 的編號對回去。
    """

    def __init__(self):
        self.count = 0  # Notify 沒有編號，用解析過的訊框數當 id
        self.pending: dict[int, tuple[str, str]] = {}  # Req 編號 -> (方法名稱, 回應類型)

    def decode(self, content: bytes, from_client: bool) -> Message:
        kind = content[0]
        if kind == NOTIFY:
            msg_id = self.count
            method, data = self._decode_notify(content[1:])
        elif kind in (REQUEST, RESPONSE):
            msg_id = unpack("<H", content[1:3])[0]
            method, data = self._decode_rpc(kind, msg_id, content[3:])
        else:
            raise ValueError(f"不認得的訊框類型 {kind}")
        self.count += 1
        return {"id": msg_id, "type": TYPE_NAMES[kind], "method": method, "data": data}

    def _decode_notify(self, body: bytes) -> tuple[str, dict]:
        s = schema()
        method, payload = s.unwrap(body)
        data = to_dict(s.parse(method.rsplit(".", 1)[-1], payload))
        if method == ACTION_PROTOTYPE:  # data 是另一個 XOR 混淆過的 protobuf
            data["data"] = to_dict(s.parse(data["name"], unmask(base64.b64decode(data["data"]))))
        return method, data

    def _decode_rpc(self, kind: int, msg_id: int, body: bytes) -> tuple[str, dict]:
        s = schema()
        name, payload = s.unwrap(body)
        if kind == REQUEST:
            request_type, response_type = s.rpc[name]
            # 同編號的舊請求還在等回應，代表那個回應沒收到，直接覆蓋
            self.pending[msg_id] = (name, response_type)
            return name, to_dict(s.parse(request_type, payload))
        if msg_id not in self.pending:
            raise ValueError(f"收到編號 {msg_id} 的回應，但沒有對應的請求（可能是代理啟動前送出的）")
        method, response_type = self.pending.pop(msg_id)
        return method, to_dict(s.parse(response_type, payload))


def unmask(data: bytes) -> bytes:
    keys = [0x84, 0x5E, 0x4E, 0x42, 0x39, 0xA2, 0x1F, 0x60, 0x1C]
    out = bytearray(data)
    for i, byte in enumerate(out):
        out[i] = byte ^ ((23 ^ len(out)) + 5 * i + keys[i % len(keys)] & 255)
    return bytes(out)
