# Conference Talk Schedule

## Reasoning

Fixed placements first: Talk F must be in the morning (constraint 4) and Talk A must be in the afternoon (constraint 5). Since A and B share a speaker (constraint 1), B must go in the morning. Since D and E cannot share a slot (constraint 3), put D in the morning and E in the afternoon. That leaves C in the afternoon, and C must be in Room 1 (constraint 2). Morning talks are therefore {F, B, D} and afternoon talks are {C, A, E} — three per slot, filling all six room-slots.

## Schedule

| Room   | Morning | Afternoon |
|--------|---------|-----------|
| Room 1 | F       | C         |
| Room 2 | B       | A         |
| Room 3 | D       | E         |

## Constraint Verification

1. **A and B not in the same time slot:** B is in the morning (Room 2), A is in the afternoon (Room 2). Different slots. ✅
2. **C must be in Room 1:** C is scheduled in Room 1 (afternoon). ✅
3. **D and E not in the same time slot:** D is in the morning (Room 3), E is in the afternoon (Room 3). Different slots. ✅
4. **F in the morning slot:** F is scheduled in the morning (Room 1). ✅
5. **A in the afternoon slot:** A is scheduled in the afternoon (Room 2). ✅

All five constraints are satisfied, and all six talks (A–F) are placed exactly once, with each room hosting exactly one talk per slot.
