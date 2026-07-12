# Data Model

## Core Entities

### Pokemon
Represents the base Pokemon identity.

Suggested fields:

- canonical_id
- display_name
- dex_number
- base_types
- default_sprite_url
- available_forms

### PokemonForm
Represents a specific form or variant.

Suggested fields:

- form_id
- pokemon_id
- form_name
- is_mega
- is_regional
- sprite_url
- type_override

### PokemonStats
Represents stat values for a specific Pokemon or form.

Suggested fields:

- hp
- attack
- defense
- special_attack
- special_defense
- speed
- total

### PokemonAbility
Represents an ability and metadata about it.

Suggested fields:

- name
- is_hidden
- slot

### PokemonMove
Represents a move that can be assigned to a team member.

Suggested fields:

- move_name
- type
- power
- accuracy
- category
- priority

### BoxEntry
Represents a Pokemon stored in the user's box.

Suggested fields:

- box_entry_id
- pokemon_id
- form_id
- notes
- tags
- created_at
- updated_at

### Team
Represents a named team.

Suggested fields:

- team_id
- team_name
- description
- created_at
- updated_at

### TeamSlot
Represents a team member assignment.

Suggested fields:

- team_slot_id
- team_id
- box_entry_id
- item
- moveset
- slot_position

## Derived Values

These should be computed from the stored data rather than manually duplicated when possible:

- total stats
- type coverage
- defensive weakness groups
- filtered and sorted views
- export rows

## Identity Rule

The most important data rule is that display text and storage identity must be different concepts.

- Display text can be friendly and localized for users.
- Storage identity should remain canonical and stable so the same Pokemon never becomes multiple records because of wording differences.
