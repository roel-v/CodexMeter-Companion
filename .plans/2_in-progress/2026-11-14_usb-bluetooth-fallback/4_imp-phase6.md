# Phase 6: documentation, artifacts and release readiness

Depends on phase 5 results. Covers R15, R16 and R21.

## Work

- Explain USB-first behaviour and full operation on PCs without Bluetooth in README/Windows/device guides.
  Cover first registration via USB, data cables, power loss, maintenance release and recovery/status messages.
- Publish a compatibility table: old/new desktop versus old/new firmware, USB capability detection, BLE fallback
  and USB-only limitations of older versions. Document that a firmware update on each display enables USB transport.
- Update changelog and prepare release notes with actual test outcomes and unresolved limits. Do not describe
  unperformed sleep, no-adapter or endurance tests as passed.
- Package the exact Windows executable and C6/Ball images validated in phase 5; do not silently rebuild them.
  If a rebuild is necessary, use explicit D: build/cache/temp paths and return to the affected phase 5 checks.
  Check D: capacity first. Retain bundles/checksums/manifests and rollback copies on E:, excluded from Git.
- Verify version metadata, identity/capabilities, packaged dependencies and artifact hashes. Include no private
  firmware backups. Prepare local installation/upgrade and rollback instructions preserving settings.
- Record commits, deviations, validation locations and remaining work in 5_post-implementation-notes.md.

## Exit

A reviewed release candidate is ready after validation. Commit/push, production installation/flashing and GitHub
publication require authorization in the active implementation task; this planning request performs none of them.
After authorized publication verify uploaded hashes and release links. Move the whole feature to 3_done only when
required work is complete; explicitly record any user-accepted deferrals rather than silently declaring completion.


## Ordered release-preparation tasks for Sol

1. Read phase 5 report and candidate manifest. Do not release with required acceptance still pending unless the user
   explicitly changes that acceptance. Preserve the approved sleep/endurance exceptions; do not request them again.
2. Update README.md, README.windows.md and docs/spotpear-ball.md with USB-first/no-Bluetooth setup, per-device modes,
   cross-PC priority, settings preservation, serial maintenance and loss-of-power limitations. Use friendly terms
   in product UI; keep protocol/version internals in developer docs. Do not imply wall-charger USB carries data.
3. Add an upgrade table with these explicit rows: old companion/old firmware unchanged BLE; new companion/old firmware
   BLE in Auto or Bluetooth-only and actionable upgrade notice in USB-only; old companion/new firmware legacy BLE
   while USB unowned; new companion/new firmware full USB/BLE feature. State legacy ownership-status limitations.
4. Update the repository's current changelog convention and dated release notes, including exact validation limits.
   Verify versions align across desktop metadata, build script, firmware identity and release manifest. Determine the
   actual next version/tag from GitHub/local state at release time, not the historical date of this plan.
5. Assemble the executable and separate C6/Ball firmware artifacts from phase 5 with instructions for the appropriate
   flash offset/tool path. Do not mix factory and application-only images. Include checksums, manifest, license and
   release notes. No private backups or diagnostic transcripts go into public assets.
6. Verify every packaged file hash against the tested candidate. If version metadata requires rebuilding, return to
   relevant phase 5 tests and update the evidence; never relabel an untested rebuilt binary as the same candidate.
7. Prepare a grouped source diff and phase-based commit boundaries for when commit/push is requested. Keep binaries,
   caches, logs and private backups ignored. Do not include unrelated changes. Update post-implementation notes.
8. When publication is authorized, push source, create a draft release, upload assets, compare uploaded digests/sizes,
   then publish as latest. Verify tag commit and public links. Use existing credential management without printing
   tokens. Do not introduce an installer or auto-update installation behaviour.
9. For authorized local deployment, preserve settings/startup location and verify the running binary version/hash,
   healthy transports and update-check path. Record any unverified physical status. Do not flash a device again if
   it already runs the exact tested firmware and no change requires it.
10. Finish with version, release URL, source commits, tested hardware, required exceptions and rollback location.
    Move the whole feature to 3_done only when the requested work is actually finished; preserve plan history.

### Rollback checklist

- [ ] Previous executable and matching firmware retained privately, with identity and hash recorded.
- [ ] Config migration rollback documented/tested; new-only mode fields do not corrupt old device registrations.
- [ ] Device settings/artwork remain intact on application upgrade, or explicit backup/restore procedure is supplied.
- [ ] If reverting to BLE-only firmware on a no-adapter PC, explain that USB operation is unavailable until upgrading.

### Exit checklist

- [ ] Documentation matches actual modes, ownership policy, compatibility and measured results.
- [ ] All release hashes match tested artifacts; versions/tag/source agree.
- [ ] No secrets, logs, backups or build outputs staged in Git.
- [ ] Publication/deployment only performed within user authorization; otherwise report candidate ready, not published.
