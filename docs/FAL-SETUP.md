# Use fal.ai for Seedance generation

Create an API key at https://fal.ai/dashboard/keys and enter it privately in this project's ignored `.env`:

```dotenv
GENERATION_PROVIDER=fal
FAL_KEY=your_private_key
REPLICATE_API_TOKEN=your_private_replicate_token
```

Restart `bash start.command`. The UI defaults to fal and still offers Enhancor. fal uses polling, so no callback tunnel is required. Replicate remains necessary for Demucs vocal separation in every preparation mode and for the default depth/SAM pipeline. This change does not move preparation inference to fal.

Run `.venv/bin/python doctor.py --require-keys --mesh`. This checks local dependencies and credential presence only. It does not validate account access, credits or face permissions and never runs paid inference. Confirm face/IP permissions with fal before spending. See [research and official sources](FAL-SEEDANCE-RESEARCH.md).

## Draft and completion

Prepare the source, review the full clip's mask or face tracking and audio, then approve those artifacts. Choose fal, add character references and review the complete prompt shown in the text area. The fal adapter submits that exact text without adding hidden creative instructions. Keep @Video1 as the source and embedded speech/performance reference, and describe identity references as appearance only. Request removal of depth colors and mesh lines, complete identity replacement including hair, and preservation of dialogue and timing.

Creating a draft is billed. The adapter uses `bytedance/seedance-2.5/us/reference-to-video`, `draft: true`, and no separate audio references. Image identity uses `task: editing`. Video identity uses `task: reference`, explicitly labeled experimental because source preservation with this combination is unverified. It retains the video identity reference rather than extracting stills. Its output duration is the source duration rounded to the nearest supported whole second, between 4 and 30, and uses the nearest supported aspect ratio. A short last-frame hold may be recorded in `duration-adjustment.json` to preserve the full soundtrack. Larger duration differences stop audio restoration rather than cutting or stretching the source audio.

Videos must be MP4/MOV, 1.8–30.2 seconds each, at most 200 MB, 24–60 FPS, 300–6000 pixels per side, and aspect ratio 0.4–2.5. All video inputs together must fit 30.2 seconds. Images must be decodable PNG/JPEG/WebP, at most 30 MB each. Validation happens before uploading to the configured public media host.

The returned queue ID and tracking URLs are persisted. Collection uses the saved provider even if the default changes, restores the entire original soundtrack and preserves the draft. fal's actual `draft_id` is saved separately from its queue ID. The UI displays a conservative expiry of 14 days from submission. Complete the draft on the same fal account using the separate, explicitly approved 1080p action. Completion is an additional full-price operation.

After a restart, the app resumes saved requests without submitting again. CLI equivalents:

```bash
.venv/bin/python workflow.py submit JOB_ID --generation-provider fal --prompt-file prompt.txt --reference character.png
.venv/bin/python workflow.py resume JOB_ID
# Only after reviewing and approving the draft and its additional cost:
.venv/bin/python workflow.py hd JOB_ID
.venv/bin/python workflow.py resume JOB_ID --hd
```

An exclusive attempt marker blocks repeat submissions after a timeout or rejected request. Check fal request history before deliberately preparing a new job. Do not remove the marker just to retry an uncertain paid request. A failed or cancelled fal queue request can report `COMPLETED`; the collector checks the result response before treating it as success. Provider credentials and authorization headers are never persisted in job artifacts.

The integration is verified with mocked provider responses and local media tests. No billed inference has validated likeness, output quality, lip synchronization, account permissions or source preservation.
