# Choose when replacement begins

Enter a start time in seconds under **Start with your video**, before preparing it. For example, `7` means the selected subject is replaced only from 00:07 onward. The complete source video and its original soundtrack are retained. Subject selection is separate: describe the intended person in **Subject to replace**, and specify that same person and the character reference in the generation prompt.

The scope is saved in `replacement-scope.json` and included in input-review fingerprints. Changing it clears approval. Depth composites use an empty subject mask before the selected time. All final exports, including approved HD completion, reconstruct the prefix from the original source video and then restore the entire original compressed audio track. The video prefix is reencoded at the generated output dimensions; original audio packets are copied unchanged. The provider still receives the full prepared video, so the start time does not reduce Seedance's billed duration.

CLI:

```bash
.venv/bin/python workflow.py prepare source.mp4 --subject "man with glasses" --replacement-start 7
```

## Short SAM chunks

Advanced preparation and original-RGB repair split normalized 24 fps video into 72-frame chunks, at most three seconds each. Frames before replacement starts are empty masks and incur no SAM inference. This reduces the peak memory of a full-clip SAM session, but each chunk is a separate paid prediction and cold starts can add overhead.

Each chunk saves its source, input hash, text prompt, attempt marker, provider response and raw-mask ZIP. Resume the same operation with the same source and settings to reuse successful chunks or poll a saved in-flight request. An ambiguous submission without an ID stops; it never repeats a paid POST automatically. Failed predictions require deliberate investigation rather than automatic resubmission.

Chunk mask indices are converted to their global source positions. Missing masks on visible content still stop the pipeline. Explicit, individually reviewed repairs can be stored under the chunk's `mask-repairs/` with provenance in `mask-repairs.json`; those files do not replace the raw SAM outputs. A missing empty white-flash frame can be recovered by the guarded compositor check. Any repair requires full-clip visual review.

Short chunks prevent one long tracking session from exhausting memory, but can reset identity tracking at boundaries or miss a person across scene cuts. Text selection is not proof of identity isolation. Review the full clip for coverage, bystanders, hands, hair, holes, alignment and flicker before generation. No mask is automatically approved.
