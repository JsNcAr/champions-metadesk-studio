"""Interactive terminal shell for box and team management."""

from __future__ import annotations

import shlex
from contextlib import contextmanager

from ..domain.entities.pokemon_move import PokemonMove
from ..domain.entities.team import Team
from ..domain.entities.team_member import TeamMember
from ..infrastructure.csv.csv_operations import export_box_entries_to_csv
from ..infrastructure.database.database import get_session
from ..infrastructure.database.repositories import BoxRepository, TeamRepository
from .pokemon_import_service import add_pokemon_to_box


class TerminalShell:
    """Minimal interactive shell for managing the local Pokemon box and teams."""

    prompt = "pokemon> "

    def run(self):
        self._print_banner()
        while True:
            try:
                line = input(self.prompt).strip()
            except EOFError:
                print()
                break

            if not line:
                continue

            should_continue = self.handle_line(line)
            if not should_continue:
                break

    def handle_line(self, line: str) -> bool:
        try:
            tokens = shlex.split(line)
        except ValueError as error:
            print(f"❌ Could not parse command: {error}")
            return True

        if not tokens:
            return True

        command = tokens[0].lower()
        args = tokens[1:]

        if command in {"exit", "quit"}:
            print("Shutting down data pipeline...")
            return False
        if command in {"help", "?"}:
            self._print_help()
            return True

        handlers = {
            "add": self._handle_add,
            "box": self._handle_box,
            "team": self._handle_team,
            "export": self._handle_export,
        }

        handler = handlers.get(command)
        if handler is None:
            print(f"❌ Unknown command: {command}. Type 'help' for options.")
            return True

        handler(args)
        return True

    def _print_banner(self):
        print("=" * 56)
        print("  Pokemon Champions Box & Team Terminal  ")
        print("=" * 56)
        print("Type 'help' to see commands, or 'exit' to close.\n")

    def _print_help(self):
        print("""
Available commands:
  add <pokemon name>
  box list
  box show <pokemon name>
  box note <pokemon name> <note>
  box tags set <pokemon name> <tag1,tag2>
  box tags clear <pokemon name>
  box favorite <pokemon name> on|off
  box delete <pokemon name>
  team list
  team create <team name>
  team show <team name or id>
  team rename <team name or id> <new name>
  team delete <team name or id>
  team add <team name or id> <slot> <pokemon name> [--item ITEM] [--ability ABILITY] [--moves MOVE1,MOVE2] [--notes NOTES]
  team remove <team name or id> <slot>
  export csv

Notes:
  - Use quotes for names with spaces.
  - Box entries are saved in SQLite and mirrored to CSV.
  - Team member assignments use box entries; the Pokemon must already be in your box.
""")

    def _handle_add(self, args: list[str]):
        pokemon_name = " ".join(args).strip()
        if not pokemon_name:
            print("❌ Usage: add <pokemon name>")
            return

        try:
            entry = add_pokemon_to_box(pokemon_name)
        except Exception as exc:  # noqa: BLE001 - the shell reports every failure the same way
            print(f"❌ Error: {exc}")
            return
        with get_session() as session:
            export_box_entries_to_csv(BoxRepository(session).list_entries())
        print(f"✅ Success: Saved '{entry.pokemon.display_name}' to SQLite and CSV.")

    def _handle_box(self, args: list[str]):
        if not args:
            print("❌ Usage: box <list|show|note|tags|favorite|delete> ...")
            return

        action = args[0].lower()
        if action == "list":
            self._box_list()
        elif action == "show":
            self._box_show(" ".join(args[1:]).strip())
        elif action == "note":
            self._box_note(args[1:])
        elif action == "tags":
            self._box_tags(args[1:])
        elif action == "favorite":
            self._box_favorite(args[1:])
        elif action == "delete":
            self._box_delete(" ".join(args[1:]).strip())
        else:
            print("❌ Unknown box command. Type 'help' for options.")

    def _handle_team(self, args: list[str]):
        if not args:
            print("❌ Usage: team <list|create|show|rename|delete|add|remove> ...")
            return

        action = args[0].lower()
        if action == "list":
            self._team_list()
        elif action == "create":
            self._team_create(" ".join(args[1:]).strip())
        elif action == "show":
            self._team_show(" ".join(args[1:]).strip())
        elif action == "rename":
            self._team_rename(args[1:])
        elif action == "delete":
            self._team_delete(" ".join(args[1:]).strip())
        elif action == "add":
            self._team_add(args[1:])
        elif action == "remove":
            self._team_remove(args[1:])
        else:
            print("❌ Unknown team command. Type 'help' for options.")

    def _handle_export(self, args: list[str]):
        if len(args) != 1 or args[0].lower() != "csv":
            print("❌ Usage: export csv")
            return

        with self._repositories() as (box_repository, _team_repository):
            export_box_entries_to_csv(box_repository.list_entries())

        print("✅ CSV export refreshed from the current SQLite box snapshot.")

    def _box_list(self):
        with self._repositories() as (box_repository, _team_repository):
            entries = box_repository.list_entries()

        if not entries:
            print("No Pokemon in the box yet.")
            return

        rows = [
            [
                entry.pokemon.display_name,
                entry.pokemon.form_name,
                ", ".join(entry.pokemon.types) or "Unknown",
                str(entry.pokemon.total),
                "yes" if entry.is_favorite else "no",
            ]
            for entry in entries
        ]
        self._print_table(["Pokemon", "Form", "Types", "Total", "Fav"], rows)

    def _box_show(self, identifier: str):
        if not identifier:
            print("❌ Usage: box show <pokemon name>")
            return

        with self._repositories() as (box_repository, _team_repository):
            entry = box_repository.load_entry(identifier)

        if entry is None:
            print(f"❌ No box entry found for '{identifier}'.")
            return

        pokemon = entry.pokemon
        print(f"Pokemon: {pokemon.display_name}")
        print(f"Canonical ID: {pokemon.canonical_id}")
        print(f"Form: {pokemon.form_name}")
        print(f"Types: {', '.join(pokemon.types) if pokemon.types else 'Unknown'}")
        print(f"Favorite: {'yes' if entry.is_favorite else 'no'}")
        print(f"Tags: {', '.join(entry.tags) if entry.tags else 'None'}")
        print(f"Notes: {entry.notes or 'None'}")
        print(
            "Stats: "
            f"HP {pokemon.stats.hp} | Atk {pokemon.stats.attack} | Def {pokemon.stats.defense} | "
            f"SpA {pokemon.stats.special_attack} | SpD {pokemon.stats.special_defense} | "
            f"Spe {pokemon.stats.speed} | Total {pokemon.total}"
        )
        if pokemon.abilities:
            print("Abilities:")
            for ability in pokemon.abilities:
                hidden_suffix = " (hidden)" if ability.is_hidden else ""
                print(f"  - {ability.name}{hidden_suffix}")
        if pokemon.available_forms:
            print("Available forms:")
            for form in pokemon.available_forms:
                print(f"  - {form.display_name}")

    def _box_note(self, args: list[str]):
        if len(args) < 2:
            print("❌ Usage: box note <pokemon name> <note>")
            return

        pokemon_name = args[0]
        note = " ".join(args[1:]).strip()

        with self._repositories() as (box_repository, team_repository):
            record = box_repository.update_metadata(pokemon_name, notes=note)
            if record is None:
                print(f"❌ No box entry found for '{pokemon_name}'.")
                return
            export_box_entries_to_csv(box_repository.list_entries())

        print(f"✅ Updated notes for '{pokemon_name}'.")

    def _box_tags(self, args: list[str]):
        if len(args) < 2:
            print("❌ Usage: box tags <set|clear> <pokemon name> [tags]")
            return

        action = args[0].lower()
        identifier = args[1]
        payload = " ".join(args[2:]).strip()

        with self._repositories() as (box_repository, team_repository):
            if action == "clear":
                record = box_repository.update_metadata(identifier, tags=[])
            elif action == "set":
                tags = [tag.strip() for tag in payload.split(",") if tag.strip()]
                record = box_repository.update_metadata(identifier, tags=tags)
            else:
                print("❌ Usage: box tags <set|clear> <pokemon name> [tags]")
                return

            if record is None:
                print(f"❌ No box entry found for '{identifier}'.")
                return

            export_box_entries_to_csv(box_repository.list_entries())

        print(f"✅ Updated tags for '{identifier}'.")

    def _box_favorite(self, args: list[str]):
        if len(args) < 2:
            print("❌ Usage: box favorite <pokemon name> on|off")
            return

        identifier = args[0]
        value = args[1].lower()
        if value not in {"on", "off", "true", "false", "yes", "no", "1", "0"}:
            print("❌ Favorite value must be on/off.")
            return

        is_favorite = value in {"on", "true", "yes", "1"}
        with self._repositories() as (box_repository, team_repository):
            record = box_repository.update_metadata(identifier, is_favorite=is_favorite)
            if record is None:
                print(f"❌ No box entry found for '{identifier}'.")
                return
            export_box_entries_to_csv(box_repository.list_entries())

        print(f"✅ Favorite status updated for '{identifier}'.")

    def _box_delete(self, identifier: str):
        if not identifier:
            print("❌ Usage: box delete <pokemon name>")
            return

        deleted = False
        removed_members = 0
        with self._repositories() as (box_repository, team_repository):
            record = box_repository.resolve(identifier)
            if record is None:
                print(f"❌ No box entry found for '{identifier}'.")
                return

            removed_members = team_repository.delete_members_by_box_entry_id(record.box_entry_id)
            deleted = box_repository.delete_by_canonical_id(record.pokemon_canonical_id)
            if deleted:
                export_box_entries_to_csv(box_repository.list_entries())

        if deleted:
            print(
                f"✅ Deleted '{identifier}' from the box"
                + (f" and removed {removed_members} team assignment(s)." if removed_members else ".")
            )
        else:
            print(f"❌ Could not delete '{identifier}'.")

    def _team_list(self):
        with self._repositories() as (_box_repository, team_repository):
            teams = team_repository.list_all()

        if not teams:
            print("No teams created yet.")
            return

        rows = []
        with self._repositories() as (_box_repository, team_repository):
            for team in teams:
                member_count = len(team_repository.list_members(team.team_id))
                rows.append([str(team.team_id), team.name, str(member_count), team.description or "-"])
        self._print_table(["ID", "Name", "Members", "Description"], rows)

    def _team_create(self, name: str):
        if not name:
            print("❌ Usage: team create <team name>")
            return

        with self._repositories() as (_box_repository, team_repository):
            existing = team_repository.get_by_name(name)
            if existing is not None:
                print(f"❌ A team named '{name}' already exists.")
                return

            team_repository.create(Team(name=name))

        print(f"✅ Created team '{name}'.")

    def _team_show(self, identifier: str):
        if not identifier:
            print("❌ Usage: team show <team name or id>")
            return

        with self._repositories() as (box_repository, team_repository):
            team_record = team_repository.resolve(identifier)
            if team_record is None:
                print(f"❌ No team found for '{identifier}'.")
                return

            members = team_repository.list_members(team_record.team_id)

            print(f"Team: {team_record.name}")
            print(f"ID: {team_record.team_id}")
            print(f"Description: {team_record.description or 'None'}")
            if not members:
                print("No team members yet.")
                return

            rows = []
            total_hp = total_attack = total_defense = total_spa = total_spd = total_speed = 0
            for member in members:
                box_entry = box_repository.load_entry(str(member.box_entry_id))
                pokemon = box_entry.pokemon if box_entry is not None else None
                if pokemon is None:
                    continue

                total_hp += pokemon.stats.hp
                total_attack += pokemon.stats.attack
                total_defense += pokemon.stats.defense
                total_spa += pokemon.stats.special_attack
                total_spd += pokemon.stats.special_defense
                total_speed += pokemon.stats.speed

                rows.append([
                    str(member.slot_position),
                    pokemon.display_name,
                    member.item or "-",
                    member.ability or "-",
                    ", ".join(move.name for move in member.moveset) or "-",
                    str(pokemon.total),
                ])

            self._print_table(["Slot", "Pokemon", "Item", "Ability", "Moves", "Total"], rows)
            print(
                "Team totals: "
                f"HP {total_hp} | Atk {total_attack} | Def {total_defense} | "
                f"SpA {total_spa} | SpD {total_spd} | Spe {total_speed}"
            )

    def _team_rename(self, args: list[str]):
        if len(args) < 2:
            print("❌ Usage: team rename <team name or id> <new name>")
            return

        identifier, new_name = args[0], " ".join(args[1:]).strip()
        if not new_name:
            print("❌ Usage: team rename <team name or id> <new name>")
            return

        with self._repositories() as (_box_repository, team_repository):
            team_record = team_repository.resolve(identifier)
            if team_record is None:
                print(f"❌ No team found for '{identifier}'.")
                return

            team_repository.rename(team_record.team_id, new_name)

        print(f"✅ Renamed team to '{new_name}'.")

    def _team_delete(self, identifier: str):
        if not identifier:
            print("❌ Usage: team delete <team name or id>")
            return

        with self._repositories() as (_box_repository, team_repository):
            team_record = team_repository.resolve(identifier)
            if team_record is None:
                print(f"❌ No team found for '{identifier}'.")
                return

            members = team_repository.list_members(team_record.team_id)
            for member in members:
                team_repository.delete_member(team_record.team_id, member.slot_position)
            team_repository.delete(team_record.team_id)

        print(f"✅ Deleted team '{identifier}'.")

    def _team_add(self, args: list[str]):
        if not args:
            print("❌ Usage: team add <team name or id> <slot> <pokemon name> [--item ITEM] [--ability ABILITY] [--moves MOVE1,MOVE2] [--notes NOTES]")
            return

        slot_index = next((index for index, token in enumerate(args) if token.isdigit()), None)
        if slot_index is None:
            print("❌ Usage: team add <team name or id> <slot> <pokemon name> [--item ITEM] [--ability ABILITY] [--moves MOVE1,MOVE2] [--notes NOTES]")
            return

        team_identifier = " ".join(args[:slot_index]).strip()
        slot_position = int(args[slot_index])
        after_slot = args[slot_index + 1 :]

        flag_index = next((index for index, token in enumerate(after_slot) if token.startswith("--")), len(after_slot))
        pokemon_identifier = " ".join(after_slot[:flag_index]).strip()
        flags = self._parse_flags(after_slot[flag_index:])

        if not team_identifier or not pokemon_identifier:
            print("❌ Usage: team add <team name or id> <slot> <pokemon name> [--item ITEM] [--ability ABILITY] [--moves MOVE1,MOVE2] [--notes NOTES]")
            return

        with self._repositories() as (box_repository, team_repository):
            team_record = team_repository.resolve(team_identifier)
            if team_record is None:
                print(f"❌ No team found for '{team_identifier}'.")
                return

            box_entry = box_repository.load_entry(pokemon_identifier)
            if box_entry is None:
                print(f"❌ No box entry found for '{pokemon_identifier}'.")
                return

            moveset = [
                PokemonMove(name=move_name.strip())
                for move_name in flags.get("moves", "").split(",")
                if move_name.strip()
            ]
            member = TeamMember(
                box_entry_id=box_entry.box_entry_id,
                slot_position=slot_position,
                item=flags.get("item") or None,
                ability=flags.get("ability") or None,
                notes=flags.get("notes") or "",
                moveset=moveset,
            )
            team_repository.upsert_member(team_record.team_id, member)

        print(f"✅ Added '{box_entry.pokemon.display_name}' to team '{team_identifier}' in slot {slot_position}.")

    def _team_remove(self, args: list[str]):
        if len(args) < 2:
            print("❌ Usage: team remove <team name or id> <slot>")
            return

        team_identifier = " ".join(args[:-1]).strip()
        slot_token = args[-1]
        if not slot_token.isdigit():
            print("❌ Slot must be a number.")
            return

        with self._repositories() as (_box_repository, team_repository):
            team_record = team_repository.resolve(team_identifier)
            if team_record is None:
                print(f"❌ No team found for '{team_identifier}'.")
                return

            deleted = team_repository.delete_member(team_record.team_id, int(slot_token))

        if deleted:
            print(f"✅ Removed slot {slot_token} from team '{team_identifier}'.")
        else:
            print(f"❌ No member found in slot {slot_token}.")

    def _parse_flags(self, tokens: list[str]) -> dict[str, str]:
        flags: dict[str, str] = {}
        current_flag: str | None = None
        current_value: list[str] = []

        def flush_current():
            nonlocal current_flag, current_value
            if current_flag is not None:
                flags[current_flag] = " ".join(current_value).strip()
            current_flag = None
            current_value = []

        for token in tokens:
            if token.startswith("--"):
                flush_current()
                current_flag = token[2:]
            else:
                current_value.append(token)

        flush_current()
        return flags

    def _print_table(self, headers: list[str], rows: list[list[str]]):
        widths = [len(header) for header in headers]
        for row in rows:
            for index, cell in enumerate(row):
                widths[index] = max(widths[index], len(cell))

        header_line = " | ".join(header.ljust(widths[index]) for index, header in enumerate(headers))
        separator = "-+-".join("-" * width for width in widths)
        print(header_line)
        print(separator)
        for row in rows:
            print(" | ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)))

    @contextmanager
    def _repositories(self):
        with get_session() as session:
            yield BoxRepository(session), TeamRepository(session)
