import json
import math

import pytest
from PIL import Image, ImageChops

from milkchan.desktop.sprites import library
from milkchan.desktop.sprites.character import STATES, Character, CharacterError, scale_layer

CANVAS = (12, 10)


def png(path, box, color=(255, 0, 0, 255), size=CANVAS):
    """A canvas-sized PNG with one filled rectangle; box=None leaves it empty."""
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new('RGBA', size)
    if box:
        image.paste(color, box)
    image.save(path)
    return path


@pytest.fixture
def sample(tmp_path):
    root = tmp_path / 'sample'
    (root / 'character.json').parent.mkdir(parents=True)
    (root / 'character.json').write_text(json.dumps({'name': 'Sample', 'faces': {'lean': 'stand'}}))
    png(root / 'stand/body.png', (2, 1, 9, 10))
    png(root / 'stand/eyes_closed.png', (4, 2, 7, 3))
    png(root / 'stand/smile/face.png', (4, 2, 7, 4), (0, 255, 0, 255))
    png(root / 'stand/smile/face_2.png', (4, 2, 7, 4), (0, 0, 255, 255))
    png(root / 'stand/smile/mouth_full.png', (5, 4, 6, 5))
    png(root / 'stand/smile/eyes_closed_2.png', (4, 2, 7, 3), (9, 9, 9, 255))
    png(root / 'stand/sad/body.png', (2, 1, 9, 10), (0, 0, 0, 255))
    png(root / 'lean/body.png', (1, 2, 11, 10))
    png(root / 'lean/sad/body_2.png', (1, 2, 11, 10), (1, 1, 1, 255))
    return root


def test_layers_fall_back_from_variant_to_mood_to_pose(sample):
    character = Character(sample)
    assert character.name == 'Sample'
    assert character.moods() == {'lean': ['neutral', 'sad', 'smile'], 'stand': ['neutral', 'sad', 'smile']}
    first = character.slots('stand', 'smile', 1)
    assert first.body == sample / 'stand/body.png'
    assert first.face == sample / 'stand/smile/face.png'
    assert first.states == {'eyes_closed': sample / 'stand/eyes_closed.png',
                            'mouth_full': sample / 'stand/smile/mouth_full.png'}
    second = character.slots('stand', 'smile', 2)
    assert second.face == sample / 'stand/smile/face_2.png'
    assert second.states['eyes_closed'] == sample / 'stand/smile/eyes_closed_2.png'
    assert second.states['mouth_full'] == sample / 'stand/smile/mouth_full.png'
    assert character.variant_count('stand', 'smile') == 2
    assert character.slots('stand', 'sad').body == sample / 'stand/sad/body.png'
    assert character.slots('stand', 'neutral').face is None
    assert first.paths('eyes_closed', None, 'mouth_half') == [first.body, first.face, first.states['eyes_closed']]


def test_borrowing_pose_uses_owner_faces_with_its_own_bodies(sample):
    character = Character(sample)
    smile = character.slots('lean', 'smile')
    assert smile.body == sample / 'lean/body.png'
    assert smile.face == sample / 'stand/smile/face.png'
    assert smile.states['eyes_closed'] == sample / 'stand/eyes_closed.png'
    assert character.variant_count('lean', 'sad') == 2
    assert character.slots('lean', 'sad', 2).body == sample / 'lean/sad/body_2.png'
    assert character.slots('lean', 'sad', 1).body == sample / 'lean/body.png'


def test_frame_is_the_box_around_every_body(sample):
    assert Character(sample).validate() == Character(sample).frame
    frame = Character(sample).frame
    assert (frame.left, frame.top, frame.width, frame.height) == (1, 1, 10, 9)


@pytest.mark.parametrize('setup, message', [
    (lambda r: png(r / 'stand/extra.png', None), 'pose folders may contain only'),
    (lambda r: png(r / 'stand/smile/happy.png', None), 'use face, body or a state name'),
    (lambda r: png(r / 'stand/smile/face_1.png', None), 'use face, body or a state name'),
    (lambda r: (r / 'empty pose').mkdir(), 'may only use letters'),
    (lambda r: (r / 'nobody').mkdir(), 'nobody/body.png is missing'),
    (lambda r: png(r / 'lean/eyes_half.png', None), 'may only contain body.png'),
    (lambda r: png(r / 'lean/smile/face.png', None), 'may only override bodies'),
    (lambda r: (r / 'character.json').write_text('{"faces": {"lean": "ghost"}}'), 'must name existing poses'),
    (lambda r: (r / 'character.json').write_text('{broken'), 'not valid JSON'),
])
def test_layout_mistakes_are_reported_clearly(sample, setup, message):
    setup(sample)
    with pytest.raises(CharacterError, match=message):
        Character(sample)


def test_canvas_size_and_empty_bodies_are_rejected(sample):
    png(sample / 'stand/smile/mouth_half.png', (1, 1, 2, 2), size=(20, 10))
    with pytest.raises(CharacterError, match='share one canvas size'):
        Character(sample).validate()
    (sample / 'stand/smile/mouth_half.png').unlink()
    png(sample / 'lean/body.png', None)
    with pytest.raises(CharacterError, match='no visible pixels'):
        Character(sample).validate()


@pytest.mark.parametrize('scale', [0.37, 0.5, 1.0, 1.07, 2.5])
def test_separately_scaled_layers_match_scaling_the_whole_canvas(scale):
    layer = Image.effect_noise((9, 7), 80).convert('RGBA')
    canvas = Image.new('RGBA', (30, 20))
    canvas.paste(layer, (13, 5))
    scaled, left, top = scale_layer(layer, 13, 5, scale)

    factor = math.ceil(scale) if scale > 1 else 1
    whole = canvas.resize((canvas.width * factor, canvas.height * factor), Image.Resampling.NEAREST)
    width, height = round(canvas.width * scale), round(canvas.height * scale)
    whole = whole.resize((width, height), Image.Resampling.BOX,
                         box=(0, 0, width * factor / scale, height * factor / scale))
    placed = Image.new('RGBA', (width, height))
    placed.paste(scaled, (left, top))
    region = (left, top, min(width, left + scaled.width), min(height, top + scaled.height))
    difference = ImageChops.difference(whole.crop(region), placed.crop(region))
    assert max(high for _, high in difference.getextrema()) <= 1


def test_import_copies_only_character_files(sample, tmp_path, monkeypatch):
    monkeypatch.setattr(library, 'library_dir', lambda: tmp_path / 'library')
    (sample / 'notes.txt').write_text('not part of the character')
    (sample / '.cache').mkdir()
    character_id = library.import_character(sample)
    copied = library.character_dir(character_id)
    assert copied.parent == tmp_path / 'library'
    assert (copied / 'stand/smile/face_2.png').exists()
    assert not (copied / 'notes.txt').exists() and not (copied / '.cache').exists()
    assert (character_id, 'Sample') in library.list_characters()
    assert library.list_characters()[0][0] == library.BUILT_IN


def test_invalid_import_leaves_nothing_behind(sample, tmp_path, monkeypatch):
    monkeypatch.setattr(library, 'library_dir', lambda: tmp_path / 'library')
    (sample / 'stand/body.png').unlink()
    with pytest.raises(CharacterError):
        library.import_character(sample)
    assert not (tmp_path / 'library').exists() or not any((tmp_path / 'library').iterdir())


def test_unknown_or_unsafe_ids_fall_back_to_the_built_in_character():
    with pytest.raises(CharacterError):
        library.character_dir('../outside')
    assert library.load_character('0' * 32).root == library.character_dir(library.BUILT_IN)


def test_renderer_draws_states_on_the_shared_frame(sample, qapp):
    from milkchan.desktop.sprites.renderer import SpriteRenderer

    renderer = SpriteRenderer(Character(sample), 90)
    assert (renderer.size.width(), renderer.size.height()) == (100, 90)
    still = renderer.render('stand', 'smile').toImage()
    blink = renderer.render('stand', 'smile', eyes='eyes_closed').toImage()
    assert still.size() == renderer.size
    assert still != blink
    assert sample / 'stand/smile/face.png' in renderer._layers
    renderer.retain('stand', 'sad')
    assert set(renderer._layers) <= set(Character(sample).slots('stand', 'sad').paths(*STATES))


def test_bundled_character_is_valid_and_every_expression_renders(qapp):
    from milkchan.desktop.sprites.renderer import SpriteRenderer

    character = library.load_character(library.BUILT_IN)
    character.validate()
    assert set(character.moods()) == {'arms_crossed', 'arms_down', 'one_arm'}
    renderer = SpriteRenderer(character, 60)
    for pose, moods in character.moods().items():
        assert moods[0] == 'neutral'
        for mood in moods:
            renderer.retain(pose, mood)
            for variant in range(1, character.variant_count(pose, mood) + 1):
                image = renderer.render(pose, mood, variant, 'eyes_closed', 'mouth_full').toImage()
                assert not image.isNull()


def test_documented_twelve_image_character(tmp_path):
    root = tmp_path / 'aiko'
    root.mkdir()
    (root / 'character.json').write_text(json.dumps({'faces': {'one_arm': 'standing', 'waving': 'standing'}}))
    for pose in ('standing', 'one_arm', 'waving'):
        png(root / pose / 'body.png', (2, 1, 9, 10))
    for state in STATES:
        png(root / 'standing' / f'{state}.png', (4, 2, 7, 3))
    for mood in ('smile', 'sad', 'mad', 'nervous', 'confused'):
        png(root / 'standing' / mood / 'face.png', (4, 2, 7, 4))
    character = Character(root)
    character.validate()
    assert len(list(root.rglob('*.png'))) == 12
    assert all(len(moods) == 6 for moods in character.moods().values())
    assert character.slots('waving', 'mad').face == root / 'standing/mad/face.png'
