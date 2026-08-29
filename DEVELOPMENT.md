# Pribambase development

This repository includes repeatable Blender 5.2, Aseprite, and PyCharm workflows. The Blender
add-on is loaded directly from the working tree, while the Aseprite client is packaged and
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
5. Install Aseprite, then run `.\client.ps1 info` to verify its executable and profile paths.
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
- **Aseprite - Build client** creates `dist/pribambase.aseprite-extension`.
- **Aseprite - Test client** builds the client and asks Aseprite to compile and smoke-test its Lua
  files in background mode.
- **Aseprite - Run client** builds the package, installs a managed development copy, and starts
  a new Aseprite instance so the updated extension is loaded. Close older instances if their
  menus make it unclear which client build is active.
- **Quality - All** runs Ruff, unit tests, the Blender smoke test, and the Aseprite client test in
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

The Aseprite client commands are:

```powershell
.\client.ps1 info
.\client.ps1 build
.\client.ps1 test
.\client.ps1 install
.\client.ps1 run
```

`build` produces both an unpacked client under `build/aseprite/pribambase` and the distributable
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
