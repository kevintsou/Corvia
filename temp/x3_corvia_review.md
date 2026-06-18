# 🔍 Multi-Agent Code Review Report

**Skill 版本：** `v1.4.0`
**審查範圍：** 自訂目標 — `D:\repo\duanyue\ws_fw`
**執行 Phase：** Phase 1 + Phase 2 (Both)
**規則來源：** general best practices (無 REVIEW_RULES.md)
**審查日期：** 2026-06-17

---

## Phase 1 — 靜態分析結果 (Corvia)

**總計：** 0 errors / 376 warnings / 572 info　（共 188 個檔案，948 issues）

| 嚴重度 | MISRA Rule | 類別 | 違規數 | 說明 |
|--------|-----------|------|--------|------|
| ⚠️ warning | MISRA 8.12 | Required | 376 | 在 enumerator list 中，以 implicit 方式指定的 enumeration constant 的值必須是唯一的 |
| ⚠️ warning | MISRA 5.9 | Advisory | 376 | 具有 internal linkage 的 object 或 function 的 identifier 應保持唯一 |
| 💡 info | MISRA 19.2 | Advisory | 188 | 不應使用 `union` 關鍵字 |
| 💡 info | MISRA 2.4 | Advisory | 8 | 專案不應包含未使用的 tag declarations |

> **Top offending file：** `src_root\yue\user\user_var.c` (13 issues)；其餘 187 個檔案各 5 issues（統一的 MISRA 模板問題）

---

## Phase 2 — 深度分析結果 (Claude Agents)

### 🔍 Line-Level Bug Issues

**[memset 誤用：U16 值被截斷，且 sizeof 參考了錯誤欄位]** — `src_root/yue/user/host/host_init.c`:492–495
Severity: **critical**
> `memset(sDtPci.aubVendorID, uwVID, sizeof(...))` 將 `U16` 的 `uwVID`（如 `0x1234`）傳入 `memset`，但 `memset` 的 fill 參數是 `unsigned char`，高位元組被靜默截斷，每個 byte 只填入低位 `0x34`，而非預期的 16-bit VID。
> 另外，`memset(sDtPci.aubSubsystemVendorID, uwSSVID, sizeof(sDtPci.aubVendorID))` 誤用了 `sizeof(sDtPci.aubVendorID)` 而非 `sizeof(sDtPci.aubSubsystemVendorID)`，若兩欄位大小不同將造成 under-fill 或 over-fill（stack buffer overflow 風險）。
> **建議修復：**
> ```c
> sDtPci.aubVendorID[0] = (U8)(uwVID & 0xFFU);
> sDtPci.aubVendorID[1] = (U8)(uwVID >> 8U);
> // 其餘欄位同理，或改用 memcpy(&sDtPci.aubVendorID, &uwVID, sizeof(uwVID))
> ```

---

**[ECC timeout 後仍檢查 r_ECC_DONE_UNC()，導致錯誤碼被覆蓋]** — `src_root/proj/ps5303/phal/bootcode_hal_efuse_api.c`:22–27
Severity: **warning**
> ECC 等待迴圈因 timeout 跳出後（`status = READ_BANK_TIMEOUT; break`），程式仍無條件執行 `if (0 != r_ECC_DONE_UNC())`。若此時 UNC bit 恰好被設置，`status` 從 `READ_BANK_TIMEOUT` 被覆寫為 `READ_BANK_DATA_UNC`，caller 收到錯誤的錯誤碼。
> **建議修復：**
> ```c
> if (READ_BANK_TIMEOUT != status && 0 != r_ECC_DONE_UNC())
>     status = READ_BANK_DATA_UNC;
> ```

---

**[PROGRAM_READY poll 無條件執行，覆蓋先前 ECC 錯誤狀態]** — `src_root/proj/ps5303/phal/bootcode_hal_efuse_api.c`:29–37
Severity: **warning**
> ECC block 結束後（無論成功或 timeout），`PROGRAM_READY` 的 mabiao poll 無條件重置並執行。若此 poll 再次 timeout，`PROGRAM_BANK_TIMEOUT` 覆蓋先前的 ECC 錯誤，最終 caller 只看到最後一個錯誤碼，原始根因消失。
> **建議修復：**
> ```c
> if (READ_BANK_DATA_NO_ERROR == status) {
>     mabiao_addr = MABIAO_SET_US(MABIAO_EFUSE, EFUSE_CMD_TIMEOUT_US);
>     while (0 == r_PROGRAM_READY()) { ... }
> }
> ```

---

**[`BC_APP_ASSERT` 後的 `if (PASS == status)` 是 dead boolean — 邏輯冗餘或 ASSERT 無效]** — `src_root/yue/app/boot/main.c`:29–32
Severity: **warning**
> `BC_APP_ASSERT(BCODE_ERROR_SEC_SELF_CHECK_FAIL, (PASS == status))` 在 release build 中若為 no-op，則缺少真正的 guard；若在所有 build 中均 abort，則 line 32 的 `if (PASS == status)` 永遠為 true，是 dead condition。兩種情況都代表邏輯不清晰。
> **建議修復：** 明確文件化 `BC_APP_ASSERT` 在所有 build 的行為；若不 abort，改為明確的 early return。

---

**[`boot_load_code_flow` 回傳 U8 但 `status` 是 U32，存在隱性截斷]** — `src_root/yue/app/boot/main.c`:9,118
Severity: **warning**
> 函數宣告回傳 `U8`，卻 `return status`（`static U32`）。若 `host_sec_kat_host` 回傳值 > 0xFF，高 24 位元被截斷，後續 `vuc_dispatch_init(status)` 收到截斷後的值，安全狀態判斷可能出錯。
> **建議修復：** 將 `boot_load_code_flow` 回傳型別改為 `U32`，或確保 `status` 只使用 8-bit 值範圍。

---

**[除以零風險：`nvme_nl_time_unit_calc` 在高頻時鐘下崩潰]** — `src_root/yue/user/host/host_init.c`:324–327
Severity: **warning**
> `sys_clk_to_ns = 1000U / sys_clk`：當 `sys_clk >= 1000`（即 >= 1 GHz）時，整數除法結果為 0，下一行 `1000U / sys_clk_to_ns` 除以零，在 ARM SDIV 指令下產生 fault。此外公式 `(1000 / (1000/clk)) - 1` 在整數截斷下不等於 `clk - 1`，300 MHz 時計算結果錯誤（332 vs 299）。
> **建議修復：**
> ```c
> U32 nl_time_unit = (sys_clk > 0U) ? (sys_clk - 1U) : 0U;
> ```

---

### 🐛 Bug & Logic Issues

**[Load KAT 失敗被 Host KAT 靜默覆蓋，加載失敗偽裝成成功]** — `src_root/yue/app/boot/main.c`:54–98
Severity: **critical**
> `host_sec_kat_load_code` 失敗且 `essential_kat_fail_stop == 0` 時，`program_loader_init` 被跳過，但 Host KAT 仍**無條件執行**（line 83：`status = host_sec_kat_host(...)`）。若 Host KAT 通過，`status` 被覆寫為 `KAT_ERROR_NONE`，第二次 KAT check 不觸發，`boot_load_code_flow` 回傳 0（成功），但韌體從未被加載。系統進入 daemon loop 卻無韌體可運行。
> **建議修復：** 在 Host KAT 前加入保護：
> ```c
> if (KAT_ERROR_NONE == prev_lc_kat_status) {
>     status = host_sec_kat_host(...);
> }
> ```

---

**[`status` 是 file-scope static，跨函數隱性傳遞導致 NULL efuse 偽裝成成功]** — `src_root/yue/app/boot/main.c`:6,118
Severity: **critical**
> 若 eFuse 指標 NULL check 失敗（外層 `if` 未進入），`status` 保持初始值 `0`（等於 `PASS`/`KAT_ERROR_NONE`），函數回傳 0 而不代表任何已完成的驗證。`main()` 接著進入 `boot_ROM_daemon_flow`，`vuc_dispatch_init(status)` 收到 0，讓 NULL eFuse 配置在行為上與成功開機無法區分。
> **建議修復：** 在函數入口將 `status` 設為哨兵錯誤值，僅在進入 if block 後才設為 PASS：
> ```c
> status = EFUSE_INIT_FAILED;
> if ((bc_ptr->p_efuse_nand_setting != NULL) && ...) {
>     status = PASS;
>     ...
> }
> ```

---

**[`eFuseToRam` 回傳值被 caller 完全忽略，未初始化 stack buffer 被當作有效 eFuse 資料]** — `src_root/yue/user/host/host_init.c`:251–253
Severity: **critical**
> `host_pcie_init` 呼叫 `eFuseToRam` 兩次但未檢查回傳值，若 eFuse 讀取失敗，`efuse_pcie_landmark_data_buf`（stack 未初始化）被直接傳入 `efuse_pcie_landmark_handle`，以隨機 stack 內容作為 PCIe landmark 配置解析，導致 PCIe 初始化行為不可預期。
> **建議修復：**
> ```c
> if (READ_BANK_DATA_NO_ERROR != eFuseToRam((U32)efuse_pcie_landmark_data_buf, EF_PCIE_LM0_BANK, FALSE))
>     goto error_handler;
> ```

---

**[`vuc_dispatch_init` 在 efuse 指標 NULL 時產生裸機空指標解引用]** — `src_root/yue/app/boot/main.c`:126
Severity: **critical**
> 若 eFuse 指標 NULL check 失敗後仍進入 `boot_ROM_daemon_flow`（因 `status` 為 0），`vuc_dispatch_init` 內部直接解引用 `gBCodeGlobalStruct.p_efuse_security_setting->vuc_protect_enable`，無任何 NULL 保護，在裸機環境下造成 CPU fault。
> **建議修復：** 在 `vuc_dispatch_init` 內部或呼叫前加入 NULL guard。

---

### 🔐 Security Issues

**[原始碼中直接嵌入 AES-XTS 與 SM4-XTS 加密金鑰]** — `src_root/yue/user/sec/encryption_key.c`:11–56
Severity: **critical**
Category: CWE-321 / OWASP A02:2021
> `gEncryptionKey_Burner` 在 `.rodata` section 中儲存完整的 256-bit AES-XTS 金鑰對（encryption_key + lba_key）與 32-byte SM4-XTS 金鑰，明文編譯進韌體二進位。任何能讀取 Flash 或韌體映像的人（JTAG、物理讀取、韌體更新包分析）皆可輕易取得這些金鑰，等同於獲得整個設備族群的 NAND 解密能力。
> **建議修復：** 從原始碼移除所有金鑰材料；金鑰應在量產時透過 eFuse/OTP 燒錄。若模擬路徑確實需要 fallback key，必須以 `#ifdef SIMULATION_ONLY` 隔離並在 production linker script 中明確排除。

---

**[KAT 失敗允許 fall-through，`essential_kat_fail_stop=0` 時設備帶破損密碼開機]** — `src_root/yue/app/boot/main.c`:54–69
Severity: **critical**
Category: CWE-754 / CWE-284
> 當 `host_sec_kat_load_code` 失敗且 `essential_kat_fail_stop == false` 時，執行不中斷。後續 Host KAT 覆蓋 `status`，第二次 check 無法感知先前失敗，設備在密碼自測失敗的狀態下完成開機。這違反 FIPS/BSI self-test 要求，創造 fail-open 條件。
> **建議修復：** KAT 失敗應無條件致命；移除 `essential_kat_fail_stop` bypass 或強制設為 `TRUE` in secure boot flow。

---

**[安全自測 skip 時 `status` 仍設為 PASS — fail-open 設計]** — `src_root/yue/app/boot/main.c`:19–31
Severity: **high**
Category: CWE-636 / OWASP A05
> `status = PASS` 在自測 guard 之前無條件執行。若 `production_mode == 0` 或 `SEC_YES` 條件不符，整個 `sec_self_check_process` 被跳過，但 `status` 已是 PASS，後續所有安全邏輯正常執行，系統不知道自測從未發生。
> **建議修復：** 初始化 `status = FAIL`，僅在每個驗證步驟通過後才更新為 PASS；或引入明確的 `SELF_CHECK_SKIPPED` 狀態以區分「通過」與「跳過」。

---

**[`eFuseToRam` 目標地址無驗證，提供任意記憶體寫入原語]** — `src_root/proj/ps5303/phal/bootcode_hal_efuse_api.c`:40
Severity: **high**
Category: CWE-822 / CWE-823
> `ulAdr` 是 caller 提供的 `U32`，被直接 cast 為 `void *` 後作為 `memcpy` 目標，無任何範圍或對齊驗證。若 caller 傳入錯誤地址（包括 NULL、中斷向量表地址、security 全局變數地址），可覆寫任意記憶體。
> **建議修復：** 驗證 `ulAdr` 是否在合法 RAM 範圍內：
> ```c
> if (ulAdr < SECURE_RAM_START || ulAdr + EFUC_BANK_SIZE > SECURE_RAM_END)
>     return ERROR_INVALID_ADDRESS;
> ```

---

**[`production_mode` 在同一 AND 條件中被重複檢查（可能 copy-paste 錯誤）]** — `src_root/yue/app/boot/main.c`:35–38
Severity: **medium**
Category: CWE-670
> `((kat_enable) && (production_mode != 0)) && ((check_code_signature_enable) && (production_mode != 0))` 對同一標誌重複 AND check，未提供任何額外保護，但可能誤導未來維護者認為有雙重保護存在。
> **建議修復：** `if (kat_enable && check_code_signature_enable && (production_mode != 0)) { ... }`

---

**[`memset` 誤用導致 PCI ID 欄位錯誤，且可能 stack buffer overflow]** — `src_root/yue/user/host/host_init.c`:492–495
Severity: **medium**
Category: CWE-131 / CWE-787
> 已於 Line-Level Bug Issues 中詳述。從安全角度，若 `aubSubsystemVendorID` 欄位因錯誤 `sizeof` 而 over-fill，可覆蓋鄰近 stack 變數，在攻擊者可控制 PCIe 設備 ID 的場景下構成潛在的 stack smash 路徑。

---

### 🎨 Style & Maintainability

#### Naming
- `src_root/yue/app/boot/main.c` line 6: File-scope static `status` 命名過於通用，語義不清。建議改為 `g_boot_load_status` 或以參數/回傳值顯式傳遞。
- `src_root/yue/app/boot/main.c` line 122: `boot_ROM_daemon_flow` 使用大寫 `ROM`，與同檔案 snake_case 風格（`boot_load_code_flow`）不一致。建議：`boot_rom_daemon_flow`。
- `src_root/proj/ps5303/phal/bootcode_hal_efuse_api.c` line 3: `eFuseToRam` 使用 camelCase，與專案主要的 snake_case 慣例不符。建議：`efuse_to_ram`。
- `src_root/proj/ps5303/phal/bootcode_hal_efuse_api.c` line 3: 參數 `ulAdr` 誤導性命名（實為目標 RAM 地址）。建議：`dst_ram_addr`。
- `src_root/yue/user/host/host_init.c` line 325: 中間變數 `sys_clk_to_ns` 在 MHz 輸入下單位不明確。建議：`ns_per_clk_cycle`。
- `src_root/yue/user/host/host_init.c` line 482: `init_smbus_variables` 實際是初始化 OCP recovery PCI descriptor，命名不準確。建議：`ocp_recovery_pci_desc_init`。
- `src_root/yue/user/sec/encryption_key.c` line 1: 標頭 comment 標示 `aes_key.c` 但實際檔名為 `encryption_key.c`。

#### Documentation
- `src_root/yue/app/boot/main.c` line 6: 未說明 `status` 為何是 file-scope static 而非函數區域變數，也未說明 `boot_ROM_daemon_flow` 透過它通信的意圖。
- `src_root/yue/app/boot/main.c` line 16: `//TODO refine this to modify the parsed out efuse values` 缺乏追蹤 reference。
- `src_root/proj/ps5303/phal/bootcode_hal_efuse_api.c` line 3: 公開函數 `eFuseToRam` 缺少參數與回傳值語義說明；四種回傳碼（`READ_BANK_TIMEOUT`、`READ_BANK_DATA_UNC`、`PROGRAM_BANK_TIMEOUT`、`READ_BANK_DATA_NO_ERROR`）無文件描述。
- `src_root/yue/user/host/host_init.c` lines 321–329: `nvme_nl_time_unit_calc` 無公式說明及單位文件。
- `src_root/yue/user/host/host_init.c` line 298: Magic MMIO 地址 `0x03116008U`、stride `0x800U` 無暫存器描述。
- `src_root/yue/user/host/host_init.c` line 315: BAR0 mask `0x7FFF` 無來源說明。
- `src_root/yue/user/sec/encryption_key.c` lines 43–46: SM4 burner 解密不支援的 TODO-style note 應進入 issue tracker。
- `src_root/yue/user/sec/encryption_key.c` lines 12–55: 大型 hex key array 缺乏金鑰用途、衍生方式、生命週期說明。

#### Complexity
- `src_root/yue/app/boot/main.c` lines 9–119: `boot_load_code_flow` 超過 100 行，混合 security self-check、load-code KAT、host KAT、program loader init、UDS KDK clearing 多個職責。建議拆分為 `boot_perform_load_code_kat()` 與 `boot_perform_host_kat()` 等輔助函數。
- `src_root/yue/app/boot/main.c` lines 54–69, 92–98: 兩段完全相同的 KAT 錯誤處理 block，應提取為 `handle_kat_failure()` helper。
- `src_root/yue/user/host/host_init.c` lines 197–262: `host_pcie_init` 處理雙 port 偵測、PERST 序列、link mode 分支、eFuse landmark 讀取、BAR 設定，建議拆分。

#### C-Specific
- `src_root/yue/app/boot/main.c` line 118: 回傳 `U8` 但 `status` 是 `U32`，隱性截斷。
- `src_root/yue/app/boot/main.c` line 126: `status` 作為 hidden cross-function 通信 channel 是脆弱設計，應改為顯式參數傳遞。
- `src_root/yue/app/boot/main.c` line 7: `extern U8 gSecAesTimeout;` 宣告後在此檔案未使用。
- `src_root/yue/user/host/host_init.c` line 20: `gVucApiCmdStruct` 具有 external linkage 但看似僅在此檔案使用，應改為 `static`。

---

## 📊 總結

**Overall verdict：** 🔴 Needs fixes

| 類別 | 問題數 |
|------|--------|
| 🔴 Critical (Bug + Security critical) | 8 |
| 🔍 Line-Level Bugs (warning) | 5 |
| ⚠️ Bug & Logic (warning) | 2 |
| 🔐 Security (high/medium) | 4 |
| 💡 Style / Info (Corvia + Style Agent) | 948 + 18 |

**Top offending files：**
1. `src_root/yue/app/boot/main.c` — 5 critical issues（status cross-function channel、KAT masking、fail-open design）
2. `src_root/proj/ps5303/phal/bootcode_hal_efuse_api.c` — 3 issues（error code overwriting、unchecked return）
3. `src_root/yue/user/host/host_init.c` — 3 issues（memset misuse、div-by-zero、unchecked eFuseToRam）

**行動建議（依優先序）：**

1. **立即修復（Critical）：**
   - `encryption_key.c`：移除 hardcoded AES/SM4 金鑰，改用 eFuse 讀取。
   - `main.c`：修正 `status` 為非 static local，或在入口初始化為錯誤值，防止 NULL efuse 偽裝成成功。
   - `main.c`：修正 Load KAT 失敗被 Host KAT 覆蓋的問題，加入顯式 early return。
   - `host_init.c`:251：檢查 `eFuseToRam` 回傳值，失敗時不傳入未初始化 buffer。

2. **高優先（High/Warning）：**
   - `host_init.c`:492–495：將所有 `memset` 改為 `memcpy`，修正 `sizeof` 參考欄位錯誤。
   - `bootcode_hal_efuse_api.c`：修正 ECC timeout 後的錯誤碼覆蓋鏈，加入 `if (NO_ERROR == status)` guard。
   - `host_init.c`:324–327：修正除以零：`nl_time_unit = sys_clk - 1U`。

3. **中優先（Medium / Style）：**
   - `main.c`：提取重複的 KAT error handling block；修正回傳型別 `U8 → U32`；移除 `extern U8 gSecAesTimeout` 未使用宣告。
   - MISRA 8.12（Required）：376 處 enumerator 值重複，為 Required 規則，若需符合 MISRA C:2012 應逐一處理。

---

## ⏱️ 執行時間

| 項目 | 時間 |
|------|------|
| 開始時間 | 15:53:24 |
| 結束時間 | 16:16:00 |
| **總耗時** | **~22m 36s** |

---

*報告由 Multi-Agent Code Review Skill v1.4.0 自動生成*
*Phase 1: Corvia 0.2.5 | Phase 2: 4 parallel Claude agents*
