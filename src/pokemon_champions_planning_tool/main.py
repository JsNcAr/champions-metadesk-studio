from .services.pokemon_import_service import append_to_spreadsheet

if __name__ == "__main__":
    print("=" * 44)
    print("  Live PokéAPI Data Pipeline Automator  ")
    print("=" * 44)
    print("Type 'exit' or 'quit' at any time to close.\n")

    while True:
        user_input = input("Enter Pokémon Name: ").strip()
        if user_input.lower() in ['exit', 'quit']:
            print("Shutting down data pipeline...")
            break
        append_to_spreadsheet(user_input)
