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

## Rebuild and validate

The generated assets are checked in so the example is ready immediately. To recreate them:

```powershell
.\sample.ps1 build
.\sample.ps1 test
```

`build` overwrites the sample `.blend`, `.png`, `.aseprite`, and `.pribambase.json` files. `test`
opens the generated scene in background Blender, validates the source pair and material link,
performs a real render, and checks that the result contains visible pixels.
