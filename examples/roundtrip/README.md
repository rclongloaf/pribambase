# Pribambase round-trip sample

This example demonstrates both directions of the Pribambase workflow:

1. pixels edited in Aseprite update a material on a Blender object;
2. Blender renders the projected object back into an Aseprite reference layer.

![Aseprite source texture](roundtrip_texture.png)
![Blender projection](roundtrip_projection.png)

## Open the sample

In PyCharm, run **Sample - Run roundtrip**. The configuration installs the current development
extension, opens `roundtrip_texture.aseprite`, and opens `pribambase_roundtrip.blend` with the current
Blender add-on source.

The same action is available from the terminal:

```powershell
.\sample.ps1 run
```

## Aseprite to Blender

1. In Blender, open the sidebar with `N`, select **Tool > Pribambase**, and press **Start Sync**.
2. In Aseprite, select **File > Pribambase: Start Sync** and wait for `Sync active`.
3. The compact **Pribambase Channels** panel opens automatically. Choose Base Color, AO,
   Roughness, Metallic, or Emission on its **Paint** tab.
4. Paint on the selected source layer. Scalar channels use grayscale values and presets.
   Base Color remains visible below the channel's default 38% preview overlay; adjust
   **Overlay Opacity** without changing the values packed into ORME.
5. Look at `AsepriteTexturedCube` in Blender using Material Preview or Rendered shading. Changes
   are transferred automatically after each Aseprite edit.

The extension sends Base Color separately and packs the scalar channels into a generated ORME image:
R = Ambient Occlusion, G = Roughness, B = Metallic, A = Emission. Blender unpacks it automatically;
the artist never has to paint directly into RGBA components.

The Blender image is named `RoundtripTexture`. It stores a portable source link to
`//roundtrip_texture.aseprite`, uses nearest-neighbor sampling, and is packed into the `.blend` so
the scene has a visible fallback before the first sync.

## Blender to Aseprite

1. Keep the connection active.
2. Change the cube or lighting. After the configured idle delay, Blender automatically
   updates the current frame's guide in Aseprite.
3. Use **Update Guide** in the 3D View panel for an immediate refresh.
4. Use **Render Dirty Frames** to update every changed animation frame.

The sample pair is configured for 12 FPS and frames 1–12. When Blender sends a guide to a frame
that does not exist yet, the Aseprite extension appends empty frames before creating the reference cel;
existing painted cels are kept intact.

Blender renders the canonical orthographic 64×64 projection with render-side anti-aliasing disabled
and sends the pixel-perfect result to the paired Aseprite document as a per-frame reference layer named
`Pribambase Render`. The reference cel is replaced on subsequent sends and does not overwrite the
painted texture layer.

The cube intentionally has no UV layer. `PB_Roundtrip_Cube_Projected` samples the texture from
fixed world coordinates, while **Restore Camera** only restores the matching inspection view.
The shared animation canvas is stored in the pair manifest and applies to all 12 frames.

## Aseprite World Normal editing

1. Start Sync in both applications. Blender sends both **Flat** polygon normals and **Smooth**
   normals for the active frame; both are already stored for all 12 frames in this migrated sample.
2. In Aseprite open **File → Pribambase: Normal Picker** and click **Paint Normals** in the Canvas group.
3. Choose Free or a 90° / 45° / 30° / 22.5° / 15° / 7.5° step. Both balls show the same camera-facing
   hemisphere with different world rotation grids, **Z → X** and **X → Z**. World axes and diagonals
   remain shared anchors; **Plane** constrains picking to XY, XZ or YZ. Paint using Aseprite's tools.
4. Use **Inspect Pixel** or **Follow cursor**. Both balls show the cyan painted direction, amber Flat
   diamond, purple Smooth triangle and white brush cross simultaneously. The inspector displays all
   three XYZ directions and both angular differences. **Use Painted / Use Flat / Use Smooth** sample
   exact RGB without snapping; hidden directions are diagnosed and cannot be copied into the brush.
5. **View Flat / View Smooth** preview either reference; **Paint Normals** returns to painting.
   Preview never changes the artist's outbound texture. **Options** reveals camera-relative numeric
   angles, overlay switches and **Geometry → Rebuild Both References** for the current frame.

Transparent paint pixels retain the Flat geometric direction. Both references are locked,
frame-exact, 64×64 RGB data maps. Rebuilding them preserves Aseprite paint. Blender's old 2×
normal source, normal picker and sculpt brushes have been removed.

The checked-in sources were upgraded with a migration, preserving the original geometry,
animation, Base Color and scalar channels:

```bash
./dev.sh pair migrate examples/roundtrip/pribambase_roundtrip.pribambase.json
```

The migrator backs up all three sources under `build/migrations/` and restores them on failure.

## Rebuild and validate

The generated assets are checked in so the example is ready immediately. To recreate them:

```powershell
.\sample.ps1 build
.\sample.ps1 test
```

`build` overwrites the sample `.blend`, `.png`, `.aseprite`, and `.pribambase.json` files. `test`
opens the generated scene in background Blender, validates the source pair and material link,
performs a real render, and checks that the result contains visible pixels.
