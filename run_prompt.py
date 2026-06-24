"""Drive Lily's /api/chat with Brett's prompt, against the live backend."""
import json, time, urllib.request

PROMPT = ("Take a look at material 107899. Should I raise, lower, or keep its "
          "forecast? Walk me through the evidence — recent forecast accuracy and "
          "bias, inventory coverage, margin, and how it's actually been selling — "
          "then give me a clear RAISE / LOWER / KEEP recommendation with your "
          "confidence level.")

# wait for health
for _ in range(40):
    try:
        if urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=3).getcode() == 200:
            print("backend up"); break
    except Exception:
        time.sleep(1)
else:
    raise SystemExit("backend did not come up")

body = json.dumps({"messages": [{"role": "user", "content": PROMPT}]}).encode()
req = urllib.request.Request("http://127.0.0.1:8000/api/chat", data=body,
                             headers={"Content-Type": "application/json"})
t0 = time.time()
resp = json.load(urllib.request.urlopen(req, timeout=300))
reply = resp.get("reply", json.dumps(resp))
with open("lily_reply.txt", "w", encoding="utf-8") as f:
    f.write(reply)
print(f"--- replied in {time.time()-t0:.0f}s, {len(reply)} chars -> lily_reply.txt ---")
