#!/usr/bin/env bash
# Records what the stub API answers for one project, which the hooks' tests replay (stub/): the thread, its state before, at and
# after the confirm_room interrupt, the streams of its design run and of the resumed run, then those of the fixture's chat turns
# (chat.json) and the state after each. Re-record when the API or the fixtures change: run the stub API (cd backend && uv run
# uvicorn app.main:app), then src/lib/mocks/record.sh [API URL].
set -euo pipefail
api=${1:-http://localhost:8000}
cd "$(dirname "$0")/stub"
body() { python3 -c "import json, sys; f = lambda n: json.load(open('../../../../../fixtures/small-bedroom/' + n + '.json')); print(json.dumps($1))"; }
post() { curl -fsSN -X POST "$api$1" -H "content-type: application/json" -d "$2"; }

post /threads '{"metadata": {"title": "Small bedroom"}}' >thread.json
url=/threads/$(python3 -c 'import json; print(json.load(open("thread.json"))["thread_id"])')
curl -fsS "$api$url/state" >state-new.json
post "$url/runs/stream" "$(body "{'input': {'photo_keys': [f('camera_pose')['photo_key']], 'dimensions': f('room_spec')['dimensions'], 'brief': f('brief')}}")" >first-run.sse
curl -fsS "$api$url/state" >state-interrupt.json
post "$url/runs/stream" "$(body "{'command': {'resume': f('room_spec')}}")" >resumed-run.sse
curl -fsS "$api$url/state" >state-done.json
for turn in 1 2; do
  post "$url/runs/stream" "$(body "{'input': f('chat')[$turn - 1]['input']}")" >chat-$turn.sse
  curl -fsS "$api$url/state" >state-chat-$turn.json
done
pnpm exec biome format --write . >/dev/null
