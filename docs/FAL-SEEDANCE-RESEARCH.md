# fal Seedance 2.5 investigation

Checked 2026-11-27. Research only. No inference, purchases, uploads, account changes, commits, or PRs. Public documentation establishes capabilities, not this account's access or output quality.

## Findings

fal supports usage-based Seedance 2.5 API calls using prepaid credits. A monthly subscription is not required for direct API usage. This is a possible provider for the workflow, but face permission remains unresolved and the video-identity editing combination needs confirmation.

### Billing

- Credits are purchased in advance and consumed by model calls. Published endpoint rates and account-specific pricing determine cost. Pricing and estimation APIs are available. This is separate from paying for a continuously running GPU. [Model API pricing](https://fal.ai/docs/documentation/model-apis/pricing)
- Purchased credits expire after 365 days. Insufficient balance can lock API access. HTTP 5xx errors and queue time are free, but invalid-input 422 errors may still incur charges if processing already used GPU time. Direct Partner API usage remains pay as you go. [FAQ](https://fal.ai/docs/documentation/model-apis/faq)
- fal's current access guide explicitly says monthly Agent plans are optional and direct API calls retain pay-as-you-go rates. It does not establish this account's balance, minimum checkout amount, or eligibility for face permissions. [Access guide](https://fal.ai/learn/tools/how-to-access-seedance-2-5-on-fal)

For TEIN, a prepared source is a video input, so use the video-reference rate and count input duration as well as output duration. Current US reference endpoint prices per 1,000 tokens are:

| Output | Without video reference | With video reference |
|---|---:|---:|
| 480p or 720p | $0.0214 | $0.0128 |
| 1080p | about $0.0234 | $0.0140 |
| 4K | $0.0094 | $0.0058 |

Approximate tokens are `output_height * output_width * (input_video_seconds + output_video_seconds) * 24 / 1024`. A second identity video therefore affects the estimate. Confirm actual dimensions and total input seconds before quoting. [US reference endpoint pricing](https://fal.ai/models/bytedance/seedance-2.5/us/reference-to-video)

1080p completion is an additional full-price call, not a credit for the draft. If its draft used video, completion uses $0.0140 per 1,000 tokens and counts input plus output duration again. [US completion pricing](https://fal.ai/models/bytedance/seedance-2.5/us/draft/complete)

### Route and input constraints

Use `bytedance/seedance-2.5/us/reference-to-video` for the prepared source plus identity references. Its `task` accepts `reference`, `editing`, `extension`, or `auto`. Image identity maps naturally to `video_urls: [prepared_source]`, `image_urls: [identity_image]`, `task: editing`. Explicitly assign @Video1 as the source and @Image1 as appearance guidance. Editing coerces duration and aspect ratio to `auto`.

The schema accepts up to 10 MP4/MOV videos, each 1.8 to 30.2 seconds, at most 200 MB each, with combined duration at most 30.2 seconds. Videos require 24 to 60 FPS, dimensions 300 to 6,000 pixels per side, and aspect ratio 0.4 to 2.5. [US API schema](https://fal.ai/models/bytedance/seedance-2.5/us/reference-to-video/api)

For video identity, the general schema can carry `[prepared_source, identity_video]`, referenced as @Video1 and @Video2. However, BytePlus's editing guide specifically documents a source video with reference images and a sole editing master. I found no equally explicit guarantee that `task: editing` accepts a second video used only for identity. Treat that combination as unverified. The general `reference` route supports multiple videos, but does not establish the same source-preservation behavior. Do not silently replace a video identity reference with stills. [Standard reference API](https://fal.ai/models/bytedance/seedance-2.5/reference-to-video/api), [BytePlus guide](https://fal.ai/learn/devs/how-to-use-seedance-2-5)

BytePlus also warns that editing preserves approximate duration, with differences up to about 0.3 seconds, and does not guarantee frame-by-frame overlap. Original-audio restoration therefore still needs duration/alignment handling. No source proves that TEIN's depth/mesh composite will produce satisfactory identity replacement. [BytePlus guide](https://fal.ai/learn/devs/how-to-use-seedance-2-5)

### Faces and permissions

Public US endpoints need no separate general access request and are available to companies worldwide. Faces and additional IP permissions may require a separate approval process through fal's team. Public endpoint access or prepaid credits does not prove these permissions are enabled. No account permission was checked or changed. [US hosting FAQ](https://fal.ai/seedance-2.5-us-hosting)

### Same-draft 1080p completion

`draft: true` produces a 480p preview and `draft_id`. Complete it through `bytedance/seedance-2.5/us/draft/complete` with that ID and `resolution: 1080p`. Current schemas specify 14 days and the original caller/same account. Completion does not accept a new creative prompt. This is documented draft continuation, not a guarantee of pixel-identical frames. Preserve the original endpoint family and account. [US draft schema](https://fal.ai/models/bytedance/seedance-2.5/us/reference-to-video/api), [US completion schema](https://fal.ai/models/bytedance/seedance-2.5/us/draft/complete/api)

Older fal tutorials still say seven days. Both current standard and US completion schemas say 14 days; prefer the current schema while keeping expiry visible in persisted metadata. Cross-provider Enhancor-to-fal draft IDs are not documented as interchangeable. [Older tutorial](https://fal.ai/learn/tools/how-to-generate-ai-videos-using-claude-and-mcp), [Standard completion schema](https://fal.ai/models/bytedance/seedance-2.5/draft/complete/api)

## Blockers and limits

1. Confirm account-specific face/IP permission before calling this generation-ready.
2. Confirm source plus video identity support in editing mode, and fit both clips within the combined 30.2-second budget.
3. Preserve provider, endpoint family, account identity, draft ID and expiry. HD completion needs its own explicit approval and additional budget.
4. Keep TEIN's full visual QA and original-audio restoration. Public API support does not validate mask quality, likeness, timing, or depth/mesh behavior.

Context7 was used after resolving `fal.ai` to `/websites/fal_ai`. It confirmed prepaid billing and expiry, but its model results returned Seedance 2.0 rather than 2.5. A query against the resolved `/websites/fal_ai_models` index also returned older/unrelated models. All 2.5-specific conclusions above therefore come from current first-party endpoint schemas and fal/BytePlus pages, not the older Context7 model results.
