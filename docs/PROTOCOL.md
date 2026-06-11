# Dell 7609WU Web Management HTTP Protocol

Reverse-engineered reference for the network control interface of the Dell
7609WU projector (web management "Version: 1.2", firmware `M0R001`). Dell never
published documentation for this API; everything below was captured from a live
unit and from the firmware's own HTML/JS.

The projector runs a minimal HTTP/1.0 server on port 80. There is no JSON API:
state is read by scraping two fixed-format HTML pages, and commands are issued
by replaying the HTML form posts the built-in web UI makes.

- [Session handling](#session-handling)
- [Authentication](#authentication)
- [Reading state](#reading-state)
- [Sending commands](#sending-commands)
- [Value enums](#value-enums)
- [RS232 cross-reference](#rs232-cross-reference)

---

## Session handling

Every request must carry the `ATOP` session cookie or the server responds with
the frameset page instead of real content.

1. `GET /` → responds `200` with the frameset and a `Set-Cookie: ATOP=...; path=/`
   header (observed value `Ros.d`).
2. Send `Cookie: ATOP=<value>` on all subsequent requests.

Notes:

- The response page `<title>` is `DELL 7609WU Web Management` — useful as a
  device-identification probe.
- Sessions expire; when a request that previously worked starts returning the
  frameset (or login page), re-fetch `/` (and re-login if needed) and retry.
- aiohttp users: the default `CookieJar` refuses cookies from bare-IP hosts, so
  track the cookie manually (or use `unsafe=True`).

## Authentication

Optional. The projector has a single firmware-fixed account, `administrator`
(the login form's user dropdown contains exactly one option). A password (max 4
characters, set via the Password Setting page) may be enabled or disabled.
`/home.htm` reports `Admin Password: Set` / `Not Set!`.

When enabled, page requests return the login page (a form posting to
`/tgi/login.tgi`) until the session cookie is authenticated:

1. `GET /login.htm` → contains a one-time nonce:
   `<input TYPE="hidden" NAME="Challenge" VALUE="...">`
2. Compute (from the firmware's own `login.js` + `md5.js`):

   ```text
   Response = md5_hex("admin" + password + challenge)
   ```

   The literal string `admin` is prepended — not the username, not
   `administrator`.
3. `POST /tgi/login.tgi` (form-urlencoded, with cookie):

   ```text
   user=0&Username=1&Password=&Challenge=&Response=<md5hex>&Submitbtn=Login
   ```

   `Password` and `Challenge` are submitted *empty* (the browser JS blanks them
   before submit). Success authenticates the `ATOP` cookie; failure returns the
   login page again.

## Reading state

### `GET /home.htm`

Device identity and summary, in label/value table rows
(`<strong>Label:</strong>` followed by the value cell):

| Field | Example | Notes |
|---|---|---|
| Group Name | `7609WU` | |
| Projector Name | `D24005` | |
| Location | | free text, may be empty |
| Contact | | free text, may be empty |
| Status | `Lamp ON` | same text as `PJSTATE2` |
| Lamp Hours | `923 hr` | |
| Firmware Version | `M0R001` | |
| IP Address | `192.168.1.100` | example value |
| MAC Address | `00:1E:C9:BA:5D:C5` | stable unique ID |
| Admin Password | `Not Set!` / `Set` | whether login is required |

### `GET /status.htm`

The "Projector Status and Control" form (`form1`, posts to `/tgi/status.tgi`).
Current state is embedded as form field values:

| Field | Type | Meaning | Values |
|---|---|---|---|
| `PJSTATE` | hidden | power state code | observed `1` while lamp on |
| `PJSTATE2` | text | power state string | `Lamp ON `, `Standby`, `Warm up`, `Cooling`, `Power Saving` |
| `DSP_SOURCE` | hidden | active source | `113`–`120` (see enums); `121` observed when no live source |
| `ERRORSTA` | hidden | error state code | `0`/`0x55` = good (per page JS) |
| `ERRORSTA2` | text | error state string | empty when OK |
| `FREEZE0` | hidden | freeze state | observed empty |
| `HIDE0` | hidden | blank screen state | `85` = hidden, `170` = visible |
| `LAMPHR` | text | lamp hours | `923 hr.` |
| `PwSave` | select | power-saving timeout | `0` off, `5`,`15`,`30`,`45`,`60`,`120` minutes (`99` = placeholder) |
| `ecoMode` | radio | lamp power | `27` = ECO, `28` = Full Power |
| `PrjMode` | select | projection mode | `0`–`3` (see enums; `99` = placeholder) |
| `PrjSRC` | select | source *to switch to* | `0` placeholder; `113`–`120` |
| `VideoMode` | select | picture preset | `0`–`4` (see enums; `99` = placeholder) |
| `hide` | radio | blank screen control | `85` on, `170` off |
| `Aspect` | radio | aspect ratio | `1` 1:1, `2` 4:3, `3` 16:9 |
| `Bright` | text | brightness | `0`–`100` |
| `Contrast` | text | contrast | `0`–`100` |
| `Volume` | text | volume | `0`–`20` |

## Sending commands

`POST /tgi/status.tgi` with `Content-Type: application/x-www-form-urlencoded`
and the `ATOP` cookie.

**Important:** the firmware expects the *entire* form state plus the clicked
submit button, exactly as a browser serializes `form1`. Always rebuild the full
payload from a fresh `/status.htm` read, change only the field you intend to
change, and add the submit button. Posting just the button (or stale values)
risks resetting other settings.

Submit buttons and their exact values (trailing spaces are significant — the
firmware string-matches them):

| Button name | Value | Paired value field |
|---|---|---|
| `PowerOn` | `Power ON ` | — |
| `PowerOff` | `Power OFF ` | — |
| `btnPwSave` | `Submit ` | `PwSave` |
| `btnECOMode` | `Submit ` | `ecoMode` |
| `btnPrjMode` | `Submit ` | `PrjMode` |
| `btnSource` | `Submit ` | `PrjSRC` |
| `btnVideo` | `Submit ` | `VideoMode` |
| `btnHide` | `Submit ` | `hide` |
| `btnAspect` | `Submit ` | `Aspect` |
| `btnBright` | `Submit ` | `Bright` |
| `btnContrast` | `Submit ` | `Contrast` |
| `btnVol` | `Submit` (no trailing space) | `Volume` |
| `btnAutoAdj` | `Auto Adjust ` | — |
| `btnReset` | `Factory Reset ` | — (avoid!) |

Captured browser payloads (power off, then power on):

```text
PJSTATE=1&DSP_SOURCE=121&ERRORSTA=&FREEZE0=&HIDE0=170&PJSTATE2=Lamp+ON+&PowerOff=Power+OFF+&PwSave=0&LAMPHR=923+hr.&ERRORSTA2=&ecoMode=27&PrjMode=1&PrjSRC=0&VideoMode=1&hide=170&Aspect=3&Bright=50&Contrast=50&Volume=12

PJSTATE=1&DSP_SOURCE=121&ERRORSTA=&FREEZE0=&HIDE0=170&PJSTATE2=Lamp+ON+&PowerOn=Power+ON+&PwSave=0&LAMPHR=923+hr.&ERRORSTA2=&ecoMode=27&PrjMode=1&PrjSRC=0&VideoMode=1&hide=170&Aspect=3&Bright=50&Contrast=50&Volume=12
```

Note the button is inserted at its DOM position (after `PJSTATE2`); other
buttons appear at their own positions in the form order. Spaces are encoded as
`+` (standard `application/x-www-form-urlencoded`).

Working `curl` example (set volume to 12):

```bash
curl -s -c jar.txt http://PROJECTOR/ > /dev/null   # get ATOP cookie
curl -s -b jar.txt http://PROJECTOR/tgi/status.tgi \
  --data 'PJSTATE=1&DSP_SOURCE=121&ERRORSTA=&FREEZE0=&HIDE0=170&PJSTATE2=Lamp+ON+&PwSave=0&LAMPHR=923+hr.&ERRORSTA2=&ecoMode=27&PrjMode=1&PrjSRC=0&VideoMode=1&hide=170&Aspect=3&Bright=50&Contrast=50&Volume=12&btnVol=Submit'
```

### Other TGI endpoints

| Endpoint | Form | Purpose |
|---|---|---|
| `/tgi/home.tgi` | `home.htm` | OSD language (`D1` 1–15 + `btnLanguage=Submit`) |
| `/tgi/login.tgi` | `login.htm` | session login (see [Authentication](#authentication)) |
| `/tgi/password.tgi` | `password.htm` | enable/disable admin password (`stateadm` 1/0 + `btn_secuadm`), set password (`new_admin`+`verify_admin`+`Submit_admin`), SNMP write community (`snmp_pwdtable`+`Submit_SNMP`) |
| `/tgi/network.tgi` | `network.htm` | network settings |
| `/tgi/email.tgi` | `email.htm` | e-mail alert settings |

## Value enums

Source (`PrjSRC` write, `DSP_SOURCE` read):

| Code | Source |
|---|---|
| 113 | VGA-A |
| 114 | VGA-B |
| 115 | S-Video |
| 116 | Composite Video |
| 117 | Component |
| 118 | DisplayPort |
| 119 | HDMI-A |
| 120 | HDMI-B |
| 121 | (observed: no active source) |

Video mode (`VideoMode`): `0` Presentation, `1` Bright, `2` Movie, `3` sRGB,
`4` Custom.

Projection mode (`PrjMode`): `0` Front-Desktop, `1` Front-Ceiling,
`2` Rear-Desktop, `3` Rear-Ceiling.

Aspect (`Aspect`): `1` 1:1, `2` 4:3, `3` 16:9 (the RS232 doc calls this
"Wide (16:10)" — the panel is WUXGA).

## RS232 cross-reference

The RS232 protocol document (`Dell 7609WU RS232 Protocol`, Rev. A00, 2008) uses
different code spaces but the same concepts; useful for interpreting values:

- System status (RS232 command `0xff`): `0x01` Standby, `0x02` Warm up,
  `0x03` Power On, `0x04` Cooling, `0x05` Power Saving — matching the
  `PJSTATE2` strings above.
- Current source (RS232 `0x26`): `0x01` VGA-A … `0x08` HDMI-B — same order as
  the HTTP codes `113`–`120` (offset by 112).
- Lamp hour (RS232 `0x2f`), firmware version (RS232 `0x30`) mirror the
  `home.htm` fields.

RS232 serial settings, for reference: 19200 bps, 8N1, no flow control.
