# Pribambase development

This repository includes repeatable Blender 5.2, Aseprite, and PyCharm workflows. The Blender
add-on is loaded directly from `blender/`, while the Aseprite extension from `aseprite/` is packaged and
installed automatically before launch.

## First-time setup on Windows

1. Install Blender 5.2.
2. Open the repository in PyCharm.
3. In the PyCharm terminal, run:

   ```powershell
   .\dev.ps1 setup
   ```

   The command recreates a broken `.venv` if needed, using Blender's bundled Python. It installs
   runtime dependencies, test tools, and Blender 5.2 API stubs for completion and inspections.

4. In **Settings | Python | Interpreter**, select `.venv\Scripts\python.exe` if PyCharm did not
   detect it automatically.
5. Install Aseprite, then run `.\aseprite.ps1 info` to verify its executable and profile paths.
6. Run the shared **Quality - All** configuration once.

Blender is auto-detected in common install locations. For a portable/custom installation, copy
`.env.example` to `.env` and set `BLENDER_EXECUTABLE`.

## Daily workflow

- **Blender - Run add-on** starts a clean Blender session and registers Pribambase from this
  checkout.
- **Blender - Debug add-on** starts Blender and waits for PyCharm on `127.0.0.1:5678` before
  importing the add-on. Start **Debug - Attach to Blender** with the Debug action after the
  waiting message appears; breakpoints in `register()` and startup code will be active.
- After editing Python files, press `F3` in Blender and run **Reload Pribambase (Dev)**.
- **Tests - Unit** runs fast tests without Blender.
- **Blender - Smoke test** starts Blender in background mode, then verifies import, registration,
  and complete unregistration.
- **Aseprite - Build extension** creates `dist/pribambase.aseprite-extension`.
- **Aseprite - Test extension** builds the extension and asks Aseprite to compile and smoke-test its Lua
  files in background mode.
- **Aseprite - Run extension** builds the package, installs a managed development copy, and starts
  a new Aseprite instance so the updated extension is loaded. Close older instances if their
  menus make it unclear which extension build is active.
- **Sample - Run roundtrip** opens a ready Aseprite texture and Blender scene demonstrating live
  texture updates and sending the rendered projection back to Aseprite.
- **Sample - Build roundtrip** regenerates the sample assets; **Sample - Test roundtrip** validates
  the source link, material, and a real 64×64 Blender render.
- **Quality - All** runs Ruff, unit tests, the Blender smoke test, and the Aseprite extension test in
  that order.

The same actions are available in the terminal:

```powershell
.\dev.ps1 info
.\dev.ps1 run
.\dev.ps1 debug
.\dev.ps1 lint
.\dev.ps1 unit
.\dev.ps1 test
.\dev.ps1 all
```

The Aseprite extension commands are:

```powershell
.\aseprite.ps1 info
.\aseprite.ps1 build
.\aseprite.ps1 test
.\aseprite.ps1 install
.\aseprite.ps1 run
```

The round-trip sample commands are:

```powershell
.\sample.ps1 info
.\sample.ps1 build
.\sample.ps1 test
.\sample.ps1 run
```

See [`examples/roundtrip/README.md`](examples/roundtrip/README.md) for the step-by-step workflow.

`build` produces both an unpacked extension under `build/aseprite/pribambase` and the distributable
`dist/pribambase.aseprite-extension`. `install` deploys it to the current Aseprite profile under
`extensions/pribambase`. The runner only replaces copies marked as development installs. If a
regular installation already exists, remove it through Aseprite or use `install --force`; the
forced path is moved to a timestamped backup before installation.

The smoke test uses Blender's `--background`, `--factory-startup`, and `--python-exit-code 1`
options. It also enables `--offline-mode`, ensuring tests never install packages or access the
network as a side effect of importing the add-on.

## Breakpoint debugging

1. Place breakpoints in the add-on source.
2. Run **Blender - Debug add-on** using the normal Run action.
3. Wait for `waiting for PyCharm DAP debugger at 127.0.0.1:5678` in the console.
4. Select **Debug - Attach to Blender** and use the Debug action.
5. Stop the DAP session before closing Blender.

The debug listener binds to loopback only. To use another local port, set `BLENDER_DEBUG_PORT` in
`.env` and update the DAP configuration to match. Pausing the main thread at a breakpoint also
pauses Blender's UI until execution resumes.

## Source-pair workflow

The round-trip sample stores the editable sources as a pair:

- `pribambase_roundtrip.blend` owns geometry, animation, light, and global projection settings;
- `roundtrip_texture.aseprite` owns painted pixels;
- `pribambase_roundtrip.pribambase.json` stores portable pair and animation settings;
- generated PNGs and Blender projections are replaceable outputs.

Run **Sample - Run roundtrip**, then press **Start Sync** in Blender and choose
**File > Pribambase: Start Sync** in Aseprite. Texture edits travel to Blender immediately.
Relevant Blender dependency-graph changes mark the current frame dirty and, when enabled, render
the guide after the configured idle delay. Incoming image updates are excluded from that detector
to prevent feedback loops.
