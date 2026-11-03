"""Voiceover (neural TTS) + captions + final cut for the Axyl failure test -> axyl_failure_test.mp4"""
import asyncio, difflib, json, pathlib, subprocess
import edge_tts

HERE = pathlib.Path(__file__).parent
VOICE, RATE = "en-US-AvaMultilingualNeural", "-4%"
LINES = [  # one line per recorded scene (frames/01_* .. 15_*)
    "If Rayls validators fail in the middle of a payment, does the payment settle, stall, or fork? I couldn't find a measured answer, so I tested it.",
    "The Rayls blog says Axyl delivers 15,000 plus TPS and sub-second finality. That's the normal case. I wanted the failure case.",
    "The docs say the Foundation operates the validators. They also tell apps to track their own submissions, and to treat a missing receipt as a drop only after a few epochs. So what does a missing receipt look like in practice?",
    "I built Axyl from source at this commit and started four validators on my laptop. Four validators tolerate one failure. Quorum is three.",
    "First, a control with nothing broken. One payment, settled in about a second.",
    "Now a real crash. Kill dash nine on validator three. The other three keep going, and a payment settles in 1.6 seconds. Across six runs, including crashing the block author, all 240 payments settled.",
    "Now I kill two, so quorum is gone, and blocks stop. The docs say this should happen. I send a payment anyway. The node returns a hash in 15 milliseconds, with no error, but no receipt comes. Nothing tells the sender the chain has stopped. The clock at the top shows real time. I restart both validators. Blocks resume, and the payment settles, 41 seconds after it was sent.",
    "Did it fork? I compare all four validators across the whole chain, including the outage. Same hashes, same balance, same nonce.",
    "Next, a double spend attempt. One nonce, two different payments, sent at the same moment to two validators. Both return a hash. Only one ever gets a receipt. In 24 trials there was one winner every time, and the balance moved by exactly one payment and its fee.",
    "Now the public testnet. Real payments, from my machine.",
    "Over 150 payments the median was 2.44 seconds, and none came in under one second. About 0.4 of that is my round trip to the RPC, and polling adds a little. This is what a client sees, which isn't the same as the finality the blog describes.",
    "Here's a full quorum loss run. The chain stops and every payment waits. The first one sent waited 69 seconds. Then all of them settle.",
    "Every test in one table. No forks, no double spends, and no lost payments in these runs. What a failure cost here was waiting.",
    "You can check all of this. One script recomputes every number from the raw data. Another changes the data eleven ways and confirms the checker rejects each one.",
    "So on this setup, it stalls. It doesn't fork. The limits: one laptop, crashes only, small samples, no mainnet payments. And one restarted validator diverged early, in a messy run. I couldn't reproduce it in eight clean trials, and I reported it privately to Rayls. The data and code are linked below.",
]
LEAD, TAIL, MAX_SPEED, MIN_SPEED = 0.3, 0.7, 2.0, 0.6
ff = lambda *a: subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *a], cwd=HERE, check=True)
dur = lambda f: float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)], cwd=HERE))


async def _tts_once(text):
    words, audio = [], bytearray()
    async for c in edge_tts.Communicate(text, VOICE, rate=RATE, boundary="WordBoundary").stream():
        if c["type"] == "audio":
            audio += c["data"]
        elif c["type"] == "WordBoundary":
            words.append({"w": c["text"], "s": c["offset"] / 1e7, "e": (c["offset"] + c["duration"]) / 1e7})
    return words, audio


async def tts(i, text):
    for attempt in range(4):  # the TTS websocket sometimes stalls; time out and retry
        try:
            words, audio = await asyncio.wait_for(_tts_once(text), timeout=60)
            break
        except Exception as e:
            print(f"  tts retry {attempt + 1}: {type(e).__name__}")
    else:
        raise RuntimeError(f"TTS failed for line {i}")
    (HERE / "vo" / f"{i:02}.mp3").write_bytes(audio)
    return words


def align(text, bounds):
    """Time each script token by its first letter, matching letter streams (TTS splits/expands tokens)."""
    norm = lambda x: "".join(ch for ch in x.lower() if ch.isalnum())
    bchars = [i for i, b in enumerate(bounds) for _ in norm(b["w"])]
    toks = text.split()
    starts = [sum(len(norm(x)) for x in toks[:i]) for i in range(len(toks))]
    tmap = {}
    for a, b, n in difflib.SequenceMatcher(None, "".join(map(norm, toks)), "".join(norm(b["w"]) for b in bounds), autojunk=False).get_matching_blocks():
        tmap.update({a + j: bchars[b + j] for j in range(n)})
    out = []
    for tok, p in zip(toks, starts):
        hit = next((tmap[q] for q in range(p, p + max(len(norm(tok)), 1)) if q in tmap), None)
        if hit is None and out:
            out[-1]["w"] += " " + tok
            continue
        out.append({"w": tok, "s": bounds[hit or 0]["s"], "e": bounds[hit or 0]["e"]})
    return out


(HERE / "vo").mkdir(exist_ok=True); (HERE / "clips").mkdir(exist_ok=True); (HERE / "seg").mkdir(exist_ok=True)
scenes = sorted(p for p in (HERE / "frames").iterdir() if p.is_dir())
assert len(scenes) == len(LINES), (len(scenes), len(LINES))
t, cues, segs = 0.0, [], []
for i, (d, text) in enumerate(zip(scenes, LINES), 1):
    words = align(text, asyncio.run(tts(i, text)))
    ff("-f", "concat", "-safe", "0", "-i", str(d / "list.txt"), "-vf",
       "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=#101418,fps=30,format=yuv420p",
       "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", f"clips/{d.name}.mp4")
    vo, c = dur(HERE / "vo" / f"{i:02}.mp3"), dur(HERE / "clips" / f"{d.name}.mp4")
    seg_d = max(vo + LEAD + TAIL, c / MAX_SPEED)
    speed = max(c / seg_d, MIN_SPEED)  # short clips play slower so the screen stays in step with the voice
    ff("-i", f"clips/{d.name}.mp4", "-i", f"vo/{i:02}.mp3", "-filter_complex",
       f"[0:v]setpts=PTS/{speed:.4f},tpad=stop_mode=clone:stop_duration={seg_d:.3f},trim=duration={seg_d:.3f},fps=30[v];"
       f"[1:a]adelay={int(LEAD * 1000)}:all=1,apad,atrim=duration={seg_d:.3f},aresample=48000[a]",
       "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "20", "-preset", "veryfast", "-pix_fmt", "yuv420p",
       "-c:a", "aac", "-b:a", "160k", f"seg/{i:02}.mp4")
    segs.append(f"{i:02}.mp4")
    chunk = []
    for j, w in enumerate(words):  # short caption chunks, broken at punctuation
        chunk.append(w)
        ends = lambda x: x["w"][-1:] in ".?:,"
        soon = any(ends(x) for x in words[j + 1:j + 3])
        if ends(w) and len(chunk) >= 2 or len(chunk) >= 6 and not soon or len(chunk) >= 8 or j == len(words) - 1:
            s = t + LEAD + chunk[0]["s"]
            e = t + LEAD + (words[j + 1]["s"] if j + 1 < len(words) else chunk[-1]["e"] + 0.4)
            cues.append((s, e, " ".join(x["w"] for x in chunk)))
            chunk = []
    print(f"scene {i}: clip {c:.1f}s vo {vo:.1f}s -> {seg_d:.1f}s at {speed:.2f}x")
    t += seg_d

stamp = lambda x: f"{int(x // 3600):02}:{int(x % 3600 // 60):02}:{int(x % 60):02},{int(x * 1000 % 1000):03}"
(HERE / "captions.srt").write_text("\n".join(f"{k}\n{stamp(s)} --> {stamp(e)}\n{c}\n" for k, (s, e, c) in enumerate(cues, 1)), encoding="utf-8")
(HERE / "seg" / "list.txt").write_text("".join(f"file '{s}'\n" for s in segs))
ff("-f", "concat", "-safe", "0", "-i", "seg/list.txt", "-c", "copy", "raw.mp4")
style = "FontName=Arial,Bold=1,FontSize=15,PrimaryColour=&H00FFFFFF,OutlineColour=&H00202020,BorderStyle=1,Outline=2.2,Shadow=1,MarginV=46"
ff("-i", "raw.mp4", "-vf", f"subtitles=captions.srt:force_style='{style}'", "-map_metadata", "-1",
   "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-c:a", "copy", "-movflags", "+faststart", "axyl_failure_test.mp4")
print(f"total {t:.1f}s -> axyl_failure_test.mp4")
