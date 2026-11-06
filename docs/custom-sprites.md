# Custom characters

A character is a folder of transparent PNGs. You draw one **body** per pose and
small **face** layers on top of it. The app combines them while it runs, so you
never draw every combination of pose, mood, blink and mouth.

Import a folder under **Settings → Character → Import folder…**. The importer
checks the folder and explains any problem. Select the character and press
**Save** to use it. The preview plays Blink, Talk and Think for every pose,
mood and variant, so you can check each layer.

## The smallest useful character

One pose, three moods, blinking, thinking and talking: **8 images**.

```text
My character/
  character.json        {"name": "Aiko"}
  standing/
    body.png            the whole character with a calm face
    eyes_closed.png     closed eyes, for blinking
    eyes_half.png       half-closed eyes, shown while she thinks
    mouth_half.png      talking, mouth half open
    mouth_full.png      talking, mouth wide open
    smile/
      face.png          the smiling face, drawn over the body
    sad/
      face.png
```

`neutral` needs no folder: it is the face already on `body.png`. Every PNG has
the same canvas size (for example 1920×1080) and the character stays in the same
place on it, so the layers line up without any coordinates. Leave everything
transparent except what the layer changes. A face layer only needs the eyes,
brows and mouth.

Add a pose by adding a folder with its own `body.png`. Add a mood by adding a
mood folder with a `face.png`.

## What each file means

| File | Where | Shown |
| --- | --- | --- |
| `body.png` | pose folder (required) | always, under everything |
| `eyes_closed.png` | pose or mood folder | during a blink |
| `eyes_half.png` | pose or mood folder | while the AI is thinking |
| `mouth_half.png`, `mouth_full.png` | pose or mood folder | alternating while talking |
| `face.png` | mood folder | the mood's resting face |
| `face_2.png`, `face_3.png`, … | mood folder | idle variants, such as a glance aside |
| `<state>_2.png`, … | mood folder | a state drawn for one variant only |
| `body.png`, `body_2.png`, … | mood folder | the mood changes the body (arms, posture) |

The app looks for a layer in this order and uses the first it finds:

1. the variant's own file in the mood folder, for example `smile/eyes_closed_2.png`
2. the mood's file, `smile/eyes_closed.png`
3. the pose's shared file, `standing/eyes_closed.png`

If none exists, that layer is simply not drawn. Draw mood-specific states only
where the shared one looks wrong, for example a mouth that must stay open in
an angry face.

Variants are picked at random after each blink, so the character glances around
on its own. Variant 1 is `face.png`; a variant exists when `face_N.png` or
`body_N.png` exists.

## Sharing faces between poses

Two poses with the same head position can share all mood faces and states:

```json
{"name": "Aiko", "faces": {"one_arm": "standing"}}
```

`one_arm/` then contains only its `body.png`, plus `<mood>/body.png` for moods
whose body differs. The built-in Milk Chan does not use this, but a new
character with three poses and six moods can be done in **12 images**: three
bodies, four states and five faces.

## Names

Pose and mood names use letters, digits, `_` and `-`. The AI picks a pose and a
mood by these names, so choose clear words such as `arms_crossed`, `smile`,
`nervous`. The AI's instructions list every pose with its moods.

## The built-in character

`milkchan/desktop/assets/characters/milkchan/` follows the same layout and is a
complete example: three poses, up to eight moods, variants and mood-specific
states. Imported characters are stored in `~/.local/share/milkchan/characters/`;
delete a folder there to remove one.

Sprite packs made for earlier MilkChan versions (one image per expression in
`~/.local/share/milkchan/sprite_packs/`) are not read any more. Redraw them as
bodies and faces, or keep the old version for them.
