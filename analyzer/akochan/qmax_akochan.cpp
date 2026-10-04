// qmax_akochan：把 akochan 的 ai_review 包成「一行請求、一行回應」的子行程，給 qmax 呼叫。
//
// akochan 自己的 pipe 模式每讀到一個別家打牌就計算一次（約一秒），回放快轉或別家連續打牌時會
// 積一大串；這裡改成只在被問時計算。這個檔案只呼叫 akochan 的函式庫（libai），不修改它。
//
// 請求（一行 JSON）：{"id": 自己的座位, "record": [mjai 事件，從 start_game 起到現在]}
//   start_game 需要 akochan 的擴充欄位 kyoku_first（東風戰 4、半莊戰 0）與 aka_flag。
// 回應（一行 JSON）：ai_review 的結果 [{"moves": [mjai 動作...], "review": {"pt_exp_total": ...}}, ...]
//   請求格式不對時回 {"error": "..."}；akochan 內部檢查失敗時會直接結束（assert）。
#include <iostream>
#include <string>

#include "ai_src/selector.hpp"

int main(int argc, char* argv[]) {
    if (argc != 2) {
        std::cerr << "usage: qmax_akochan <tactics json>" << std::endl;
        return 2;
    }
    set_tactics_one(load_json_from_file(argv[1]));
    std::cout << "QMAX_AKOCHAN_READY" << std::endl;

    std::string line, err;
    while (std::getline(std::cin, line)) {
        const json11::Json request = json11::Json::parse(line, err);
        if (!err.empty() || !request["record"].is_array() || !request["id"].is_number()) {
            std::cout << json11::Json(json11::Json::object{{"error", "bad request: " + err}}).dump() << std::endl;
            continue;
        }
        const Moves record = request["record"].array_items();
        std::cout << ai_review(record, request["id"].int_value()).dump() << std::endl;
    }
    return 0;
}
