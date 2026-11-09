from dataclasses import dataclass


@dataclass(frozen=True)
class Game:
    code: str
    name: str
    data_file: str
    kind: str
    main_count: int
    max_number: int
    special_max: int | None = None


GAMES = {
    game.code: game
    for game in (
        Game("power655", "Power 6/55", "power655.jsonl", "draw", 6, 55, 55),
        Game("power645", "Power 6/45", "power645.jsonl", "draw", 6, 45),
        Game("power535", "Power 5/35", "power535.jsonl", "draw", 5, 35, 12),
        Game("keno", "Keno", "keno.jsonl", "keno", 20, 80),
        Game("3d", "Max 3D", "3d.jsonl", "digits", 1, 999),
        Game("3d_pro", "Max 3D Pro", "3d_pro.jsonl", "digits", 1, 999),
    )
}


def get_game(code: str) -> Game:
    try:
        return GAMES[code]
    except KeyError as exc:
        supported = ", ".join(GAMES)
        raise ValueError(f"Game không hợp lệ: {code}. Chọn một trong: {supported}") from exc


def game_choices() -> tuple[str, ...]:
    return tuple(GAMES)
