#!/bin/bash
# Ensure we are in the script's directory
cd "$(dirname "$0")"

# Load existing ../.env to read current default
CURRENT_BACKEND=$(grep -E '^OCR_BACKEND=' ../.env 2>/dev/null | cut -d= -f2 | tr -d ' ' || echo "local")

echo ""
cat << 'EOF'
                                                  :-===::..
                                                ::-::+***######*++==-::..
                                               -*-.        .::--==+++*****#**++==--::.::
                                              :#=.                       ..::-==++*+===...
                                              =:::-==-::...                       :-.-..
                                        .::-----:  ::-===+++++==--:...            *=*.
                                  .:---=---..**+-:.-..:  :  :..---====++++===-::.*-*=
                           ..:--===-:- :. - :+==- .:.:-:-=--=-:-:...  .   -:::=+*+.*.
                      .::-====--. :  :.:::-.=-:=:..: ..  .  . .-::=---=--:-  .:::--=
                .:--=====-: :  :..-::- :. : ----..:-:-----:::..:  .  .:.-=----:-==*.
         ..::--====-:.:  .  ::::. :  : ::.:.-.::.       ...::.---==--=-===-.  .=-=+
      ==-::::::-. ..  :.:::... .. ::.-.:  : ::::.::::-:.:  ...:-===-:-..:.-:-:=-:+.
     .*#**++-..:  .:..:  .  .:.::.:  : :::-.::--  .  ::-==-=====-=+=--::--- :-= =+
      -#@@@@%%%##*+=:.:..::... .  :..-::. . .:::  ..:-=======:.=  =+=-:::---=+:.=:
        +*=+**#%%%%%%%%##*+---.::.:. : .  :-----==++++=--..:--==:--=:. . :.-=: ++
      .+++: :  --==++*#%%%%%%%##*+=:.::--=-++++++++=-::.-:--:::: :.---=:=--== :+-
       :=*+-==--: ::..-:.-==*#%%%%+::.:...-*%*+=..  .:-=-==--:-: -::. : .-=++:-+
         += --:==-=+-.-. .. .----++--::::-=++---=--:-. . :.-:==---:::.:.-==: .+:
       ::+=::: :: :=:.-======-.  .: .-:-:-:-===::--:-::-:---..: -:.:----===. -+
       -+++-.-  - .=:.::..-.:----=--=-::.:.--:-:.-.:-:--:--..:-.=-:: . .-=::.=-
         .*+=+--=---: .:  : ::-::--:==--:::=-.====++=-=-:==-:-:.:..:.---=:  :=
        ::+=:=:.=-:+=:--::-:.::..:-:::--:::==-=======+=+++++==-:::--:::--...--
        ======. -: ==--==++-:--:::=::.-:::-==---=========+=======++=+-.=:...-
          -==+==+=::-  -:-=--=+++=---:--:--==-======================+:-=.  ::
        .:--::-.-=-=+=-=::=:::-::==-=-----======================----..--=+-.
        :==----.:-:-=-==+++=--=====-=======================-=----::::=---:.
           +==+===-==-===+++**+***==++=====================--------:.    .-*-
         :==+==+*+**++*+=++=++=++*=++=----=-=-=========-=====-==-==-::.    :=:
         .=++#=-+++*+*#++**=**=+**==+++==+===---------==-----:.    .::-===---=
            .:-=*+=*+-**+**=**=+**==+++++==---===-::::::.::               .::::
                 .:==+**-+*++*++**==+=-----=====-==-:.   .++.               :*=
                      .:-=*++**-+*+=++++++=----=-:.        -=.           .:---.
                         :-++++=*#+=+-:::--==:.             -=       .:---=-.
                    :-++=--:.   .:::-:::::..                 -- .::---:.---.
                  .%%=-:.....                                =-==-:.    .--
                  .+%#+*:::.                             :-===-:         --
                   :*%%%#+=-                         .:-==-:.
                      -=*#%%#*-.                  .:---:.
                         .--+#####+-.         .:--=-:                            .
                               :-+###+-...:-=+++-.
                                    .::::---==--
                                            ----
                                          . :---
                                             ..
EOF
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║           I have the receipts – OCR Backend                  ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  1) Local   – LM Studio (Port 1234)          private         ║"
echo "║  2) Local   – Ollama    (Port 11434)         private         ║"
echo "║  3) Cloud   – Google Gemini API              needs key       ║"
echo "║  4) Cloud   – OpenRouter, no training        needs key       ║"
echo "║  5) Cloud   – OpenRouter, allow training     needs key       ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  4 refuses providers that train on your receipts. Every      ║"
echo "║    ':free' model is served only by such providers, so free   ║"
echo "║    models return 404 here — 4 needs a paid model.            ║"
echo "║  5 accepts training on your receipt data. This is the only   ║"
echo "║    way the free tier works. 50 requests/day.                 ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo -n "  Choose backend [current: $CURRENT_BACKEND] (press Enter to keep): "
read -r CHOICE

case "$CHOICE" in
  1)
    NEW_BACKEND="local"
    NEW_MODEL="qwen/qwen2.5-vl-7b"
    NEW_URL="http://localhost:1234/v1"
    ;;
  2)
    NEW_BACKEND="local"
    NEW_MODEL="llama3.2-vision:11b"
    NEW_URL="http://localhost:11434/v1"
    ;;
  3)
    NEW_BACKEND="gemini"
    NEW_MODEL="gemini-2.0-flash"
    NEW_URL=""
    ;;
  4)
    # OpenRouter with provider.data_collection=deny (the app's default).
    NEW_BACKEND="openrouter"
    NEW_MODEL="nvidia/nemotron-nano-12b-v2-vl:free"
    NEW_URL=""   # OpenRouter ignores OCR_BACKEND_URL — see ocr._local_backend_url
    NEW_TRAINING="0"
    ;;
  5)
    NEW_BACKEND="openrouter"
    NEW_MODEL="nvidia/nemotron-nano-12b-v2-vl:free"
    NEW_URL=""
    NEW_TRAINING="1"
    ;;
  "")
    NEW_BACKEND="$CURRENT_BACKEND"
    NEW_MODEL=$(grep -E '^OCR_MODEL=' ../.env 2>/dev/null | cut -d= -f2 || echo "llava:7b")
    NEW_URL=$(grep -E '^OCR_BACKEND_URL=' ../.env 2>/dev/null | cut -d= -f2 || echo "http://localhost:1234/v1")
    ;;
  *)
    echo "  Invalid choice — keeping current backend: $CURRENT_BACKEND"
    NEW_BACKEND="$CURRENT_BACKEND"
    NEW_MODEL=$(grep -E '^OCR_MODEL=' ../.env 2>/dev/null | cut -d= -f2 || echo "llava:7b")
    NEW_URL=$(grep -E '^OCR_BACKEND_URL=' ../.env 2>/dev/null | cut -d= -f2 || echo "http://localhost:1234/v1")
    ;;
esac

# Update ../.env
if [ -f "../.env" ]; then
  # Replace in place (macOS + Linux compatible)
  sed "s/^OCR_BACKEND=.*/OCR_BACKEND=$NEW_BACKEND/" ../.env > ../.env.tmp && mv ../.env.tmp ../.env

  if grep -q "^OCR_MODEL=" ../.env; then
    sed "s|^OCR_MODEL=.*|OCR_MODEL=$NEW_MODEL|" ../.env > ../.env.tmp && mv ../.env.tmp ../.env
  else
    echo "OCR_MODEL=$NEW_MODEL" >> ../.env
  fi

  if [ -n "$NEW_URL" ]; then
    if grep -q "^OCR_BACKEND_URL=" ../.env; then
      sed "s|^OCR_BACKEND_URL=.*|OCR_BACKEND_URL=$NEW_URL|" ../.env > ../.env.tmp && mv ../.env.tmp ../.env
    else
      echo "OCR_BACKEND_URL=$NEW_URL" >> ../.env
    fi
  fi
else
  echo "OCR_BACKEND=$NEW_BACKEND" >> ../.env
  echo "OCR_MODEL=$NEW_MODEL" >> ../.env
  if [ -n "$NEW_URL" ]; then echo "OCR_BACKEND_URL=$NEW_URL" >> ../.env; fi
fi

# Only written when options 4/5 were chosen — pressing Enter leaves whatever
# training preference is already on file untouched.
if [ -n "$NEW_TRAINING" ]; then
  if grep -q "^OPENROUTER_ALLOW_TRAINING=" ../.env 2>/dev/null; then
    sed "s|^OPENROUTER_ALLOW_TRAINING=.*|OPENROUTER_ALLOW_TRAINING=$NEW_TRAINING|" ../.env > ../.env.tmp && mv ../.env.tmp ../.env
  else
    echo "OPENROUTER_ALLOW_TRAINING=$NEW_TRAINING" >> ../.env
  fi
fi

echo ""
echo "  ✓ OCR backend set to: $NEW_BACKEND ($NEW_MODEL)"
echo ""

if [ "$NEW_BACKEND" = "openrouter" ]; then
  if ! grep -qE '^OPENROUTER_API_KEY=.+' ../.env 2>/dev/null; then
    echo -e "\033[1;31m  ✗ OPENROUTER_API_KEY is not set in .env — OCR will fail.\033[0m"
    echo "    Get a free key at https://openrouter.ai/keys (no payment method needed)."
    echo ""
  fi

  CURRENT_TRAINING=$(grep -E '^OPENROUTER_ALLOW_TRAINING=' ../.env 2>/dev/null | cut -d= -f2 | tr -d ' ')
  if [ "$CURRENT_TRAINING" = "1" ]; then
    echo -e "\033[1;33m  ⚠ Training opt-in is ON.\033[0m"
    echo "    Your receipts — store, items, prices, dates — are sent to OpenRouter"
    echo "    and the serving provider may retain and train on them."
    echo "    Free tier allows 50 requests/day (1000 after \$10 of credits)."
  else
    echo "  🔒 Sending provider.data_collection=deny — providers that train on"
    echo "     your data are refused."
    echo -e "\033[1;33m     Note: every ':free' model is served only by such providers, so\033[0m"
    echo -e "\033[1;33m     free models return 404 in this mode. Use a paid model (with\033[0m"
    echo -e "\033[1;33m     OPENROUTER_ALLOW_PAID=1), pick option 5, or use option 1/2 for\033[0m"
    echo -e "\033[1;33m     fully private local OCR.\033[0m"
  fi
  echo ""
fi

if [ "$NEW_BACKEND" = "local" ]; then
  while true; do
    echo "  Checking if local OCR backend is running at $NEW_URL..."
    if curl -s -f --max-time 3 "$NEW_URL/models" > /dev/null; then
      echo "  ✓ Local backend is responding."
      echo ""
      break
    else
      echo -e "\033[1;31m  ✗ Local backend is NOT responding.\033[0m"
      echo "  Please start LM Studio / Ollama, load a vision model, and ensure the local server is running."
      echo -n "  Press Enter to check again, or type 'skip' to ignore: "
      read -r CHECK_CHOICE
      if [ "$CHECK_CHOICE" = "skip" ]; then
        echo ""
        break
      fi
      echo ""
    fi
  done
fi

# The app has no authentication, so bind to loopback by default. To reach it
# from a phone or another machine, put Tailscale in front rather than widening
# the bind: `tailscale serve --bg 8000` publishes it to your tailnet over HTTPS
# and proxies to 127.0.0.1, so loopback is all it needs.
# Widen deliberately with:  HOST=0.0.0.0 ./start_server.sh
HOST="${HOST:-127.0.0.1}"

echo "Starting server on ${HOST}:8000..."
if [ "$HOST" = "0.0.0.0" ]; then
    echo -e "\033[1;33m  ⚠ Bound to all interfaces — the app has no authentication.\033[0m"
fi
# Check for SSL certificates
if [ -f "certs/server.crt" ] && [ -f "certs/server.key" ]; then
    echo "  [SSL] Certificates detected. Starting in HTTPS mode..."
    ./.venv/bin/python -m uvicorn app.main:app --reload --host "$HOST" --port 8000 \
        --ssl-certfile certs/server.crt \
        --ssl-keyfile certs/server.key
else
    echo "  [HTTP] No certificates detected. Starting in standard mode."
    ./.venv/bin/python -m uvicorn app.main:app --reload --host "$HOST" --port 8000
fi
