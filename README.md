# Telegram Card Auto Catcher

ဤ project သည် **ခွင့်ပြုထားသော Telegram group** အတွက်သာ အသုံးပြုရန် ရည်ရွယ်ထားသော Telethon user-account automation ဖြစ်သည်။ သတ်မှတ်ထားသော group ထဲသို့ task message ကို ၄ စက္ကန့်တစ်ခါ ပို့ပေးပြီး `New Waifu Is Here` spawn post တွေ့လျှင် သတ်မှတ်ထားသော catcher bot ထံ forward လုပ်ကာ bot ထံမှ ပြန်လာသော `/guess ...` နှင့် `/sudo ...` command များကို မူလ group ထဲသို့ ပြန်ပို့ပေးသည်။

> **အရေးကြီးသော သတိပေးချက်:** Telegram account session string သည် login credential တစ်ခုဖြစ်သည်။ GitHub repository, issue, screenshot သို့မဟုတ် chat ထဲ မတင်ပါနှင့်။ Render Environment Variables ထဲတွင်သာ ထည့်ပါ။ ဒီ code ကို သင်ပိုင် သို့မဟုတ် ခွင့်ပြုချက်ရှိသော group များတွင်သာ သုံးပြီး Telegram စည်းမျဉ်းများနှင့် group စည်းကမ်းများကို လိုက်နာပါ။ Flood-wait ဖြစ်လျှင် code သည် ပို့ခြင်းကို ခဏရပ်ပြီး Telegram ပြောသော အချိန်ကို စောင့်ပါမည်။

## လက်ရှိ configuration

| Setting | Value |
|---|---:|
| Group ID | `-1004378413999` |
| Catcher bot ID | `8506436817` |
| Task interval | `4` seconds |
| Task text | `task လုပ်ပါ` |
| Spawn marker | `New Waifu Is Here` |

## လုပ်ဆောင်ပုံ

1. Telegram user account သည် group ထဲကို `task လုပ်ပါ` ကို ၄ စက္ကန့်တစ်ခါ ပို့သည်။
2. Group message တစ်ခုတွင် `New Waifu Is Here` စာသားနှင့် media ပါလာပါက spawn post ဟု သတ်မှတ်သည်။
3. Spawn post ကို `8506436817` သို့ forward လုပ်သည်။
4. Catcher bot ထံမှ ပြန်လာသော message များထဲတွင် `/guess ...` နှင့် `/sudo ...` ပါလျှင် command နှစ်ခုကို group ထဲသို့ ပြန်ပို့သည်။
5. တစ်ခုတည်းသော spawn post ကို process restart မဖြစ်မချင်း ထပ်မပို့ရန် memory ထဲတွင် deduplicate လုပ်ထားသည်။
6. Group ထဲမှ ခွင့်ပြုထားသော user သည် `/stop` ပို့လျှင် task message loop ကို ရပ်ပြီး `/start` ပို့လျှင် ပြန်စသည်။ Spawn forwarding နှင့် bot result listener က ဆက်လက်အလုပ်လုပ်နေမည်။

## `/start` နှင့် `/stop`

Service စတင်ချိန်တွင် task loop သည် အလိုအလျောက် start ဖြစ်သည်။ Group ထဲတွင် `/stop` ပို့လျှင် ၄ စက္ကန့်တစ်ခါ `task လုပ်ပါ` ပို့ခြင်းကိုသာ ရပ်မည်။ `/start` ပို့လျှင် task loop ပြန်စမည်။ Control command ကို မူလ Telegram account ကိုယ်တိုင်က ပို့လျှင် အလိုအလျောက်ခွင့်ပြုထားသည်။ အခြား Telegram user များကို ခွင့်ပြုလိုပါက `CONTROL_USER_IDS` တွင် comma-separated numeric IDs ထည့်ပါ။

`keep_alive.py` သည် ပေးထားသော shared file ကို project အတွက် ပြန်ညှိထားသော version ဖြစ်ပြီး `/`, `/health`, `/healthz` health routes နှင့် အနည်းဆုံး ၆၀ စက္ကန့် interval ရှိသော self-ping loop ပါသည်။ Self-ping သည် liveness aid သာဖြစ်ပြီး Render Free spin-down သို့မဟုတ် restart ကို အာမခံတားဆီးပေးမည် မဟုတ်ပါ။

## Approach နှစ်မျိုး၏ ကွာခြားချက်

| Approach | Tradeoffs | Cost | Setup complexity |
|---|---|---:|---:|
| Render Free web service | စတင်ရန်လွယ်ကူပြီး computer ကို အမြဲဖွင့်ထားစရာမလိုပါ။ သို့သော် idle spin-down, restart, ephemeral filesystem နှင့် outbound-traffic limitation များကြောင့် ၂၄/၇ အလုပ်လုပ်မည်ဟု မအာမခံနိုင်ပါ။ | Free tier | အလယ်အလတ် |
| ကိုယ်ပိုင် computer သို့မဟုတ် အမြဲဖွင့်ထားသော server | Telethon connection သည် ပိုတည်ငြိမ်နိုင်ပြီး local session file ကို ထိန်းချုပ်နိုင်သည်။ သို့သော် computer/server သည် အမြဲ online ဖြစ်ရမည်။ | ရှိပြီးသားစက်သုံးလျှင် အပိုကုန်ကျစရိတ်မရှိ | အလယ်အလတ် |

Render ၏ Free web service သည် inbound traffic မရှိလျှင် ၁၅ မိနစ်အကြာတွင် spin down ဖြစ်နိုင်ပြီး local filesystem သည် restart, redeploy သို့မဟုတ် spin-down ဖြစ်တိုင်း ပျောက်နိုင်သည် [1]။ ထို့ကြောင့် ဤ repository သည် **စမ်းသပ်ခြင်းနှင့် hobby use** အတွက် သင့်တော်ပြီး အရေးကြီးသော ၂၄/၇ catcher အတွက် အမြဲဖွင့်ထားသော host ကို စဉ်းစားသင့်သည်။

## Local session string ပြုလုပ်ခြင်း

`api_id` နှင့် `api_hash` ကို [my.telegram.org](https://my.telegram.org) မှ ရယူပါ။ ပြီးလျှင် local machine တွင် အောက်ပါအတိုင်း run ပါ။

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/generate_session.py
```

Script က phone number, Telegram login code နှင့် two-step verification password ရှိပါက password ကို မေးပါမည်။ ပြီးလျှင် `SESSION_STRING` ကို ထုတ်ပေးပါမည်။ အဲဒီ string ကို **local file ထဲ မသိမ်းဘဲ** Render Environment Variables ထဲသို့ copy လုပ်ပါ။ `SESSION_STRING=` prefix, quotation marks, code block backticks နှင့် line break များ မပါစေရပါ။ လက်ရှိ code သည် အပြင်ဘက် quotation/prefix တချို့ကို ပြန်ဖြုတ်ပေးသော်လည်း placeholder (`replace-me`) ကို reject လုပ်မည်။

> Telegram user account session တစ်ခုကို Telethon `TelegramClient` ဖြင့် အသုံးပြုနိုင်ပြီး `api_id` နှင့် `api_hash` ကို `my.telegram.org` မှ ရယူရသည် [2]။

## Render deployment

1. GitHub တွင် repository ကို private အဖြစ်ထားပြီး push လုပ်ပါ။
2. Render Dashboard တွင် **New → Web Service** ကိုရွေးပြီး repository ကို ချိတ်ပါ။
3. Instance type ကို Free ရွေးပါ။
4. Environment Variables တွင် အောက်ပါ values များထည့်ပါ။

| Environment variable | ထည့်ရမည့်အရာ |
|---|---|
| `API_ID` | `my.telegram.org` မှ numeric API ID |
| `API_HASH` | `my.telegram.org` မှ API hash |
| `SESSION_STRING` | local script က ထုတ်ပေးသော အရှည်ကြီးသော Telethon string ကိုသာ ထည့်ပါ။ `replace-me` မထည့်ပါနှင့် |
| `GROUP_ID` | `-1004378413999` |
| `CATCH_BOT_ID` | `8506436817` |
| `TASK_TEXT` | `task လုပ်ပါ` |
| `TASK_INTERVAL_SECONDS` | `4` |
| `SPAWN_MARKER` | `New Waifu Is Here` |
| `BOT_REPLY_TIMEOUT_SECONDS` | `25` |
| `CONTROL_USER_IDS` | Optional; ဥပမာ `123456789,987654321` |
| `SELF_PING_URL` | Optional; Render public URL + `/healthz` မဟုတ်ဘဲ base URL သာ ထည့်ပါ |
| `SELF_PING_INTERVAL` | `180` seconds; code က ၆၀ ထက်နည်းလျှင် ၆၀ သို့ညှိမည် |
| `SELF_PING_START_DELAY` | `10` seconds |
| `SELF_PING_TIMEOUT` | `10` seconds |
| `PORT` | Render က အလိုအလျောက်ထည့်ပေးလျှင် မပြောင်းပါနှင့် |

`render.yaml` ပါသဖြင့် Build Command ကို `pip install -r requirements.txt` နှင့် Start Command ကို `python main.py` ထားနိုင်သည်။ Render Free service တွင် service restart ဖြစ်နိုင်သဖြင့် `SESSION_STRING` ကို persistent local file အဖြစ် မထားဘဲ environment variable အဖြစ် အသုံးပြုထားသည်။

## လုံခြုံရေးနှင့် Telegram ကန့်သတ်ချက်များ

Telegram Bot API သည် bot များက အခြား bot များပို့သော message ကို မမြင်နိုင်ရန် ကန့်သတ်ထားသည် [3]။ ထို့ကြောင့် ဤ project သည် **user account session** ဖြင့် catcher bot ကို forward လုပ်ပြီး bot ၏ reply ကို လက်ခံရန် ရေးထားသည်။ Bot token တစ်ခုတည်းဖြင့် ဤ workflow ကို အစားထိုးရန် မသင့်တော်ပါ။

Task interval ကို ၄ စက္ကန့်အောက်သို့ မလျှော့ပါနှင့်။ Telegram က flood-wait ပြန်ပေးလျှင် Telethon နှင့် code သည် အလိုအလျောက် backoff လုပ်မည်ဖြစ်သော်လည်း repeated automation ကြောင့် account restriction ဖြစ်နိုင်ခြေရှိသည်။ Group admin ခွင့်ပြုချက်နှင့် bot ၏ လိုအပ်သော access ရှိကြောင်း သေချာစစ်ဆေးပါ။

## Local run

```bash
export API_ID='123456'
export API_HASH='replace-me'
export SESSION_STRING='replace-me'
export GROUP_ID='-1004378413999'
export CATCH_BOT_ID='8506436817'
export TASK_TEXT='task လုပ်ပါ'
export TASK_INTERVAL_SECONDS='4'
export SPAWN_MARKER='New Waifu Is Here'
python main.py
```

Health check ကို `http://localhost:8080/health` တွင် စစ်နိုင်သည်။ `/start` နှင့် `/stop` command များကို သင့် group ထဲမှ ခွင့်ပြုထားသော account ဖြင့် ပို့ပါ။ Render တွင် `ValueError: Not a valid string` ဖြစ်ပါက `SESSION_STRING` ကို အမှန်တကယ် generate ပြန်လုပ်ပြီး Render Environment Variable ကို အစားထိုးကာ redeploy လုပ်ပါ။

## References

[1]: https://render.com/docs/free "Render: Deploy for Free"
[2]: https://docs.telethon.dev/en/stable/modules/client.html "Telethon TelegramClient documentation"
[3]: https://core.telegram.org/bots/faq "Telegram Bots FAQ"
