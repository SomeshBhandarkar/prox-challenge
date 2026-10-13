# Fact-check checklist

How to use: open the PDF page (or the PNG next to this file), compare each line, and tick the box. If anything is wrong, tell me the line and the right value.

Files being checked: `knowledge/data/specifications.json` and `knowledge/data/controls.json`.

## 1. Specifications (manual page 7)
Open `knowledge/factcheck/page-07.png` (or page 7 of `files/owner-manual.pdf`).

### MIG

| Field | 120V | 240V |
|---|---|---|
| Current input at output | 20.8A at 100A | 25.5A at 200A |
| Welding current range | 30-140 A | 30-220 A |
| Rated duty cycles | 40% @ 100A; 100% @ 75A | 25% @ 200A; 100% @ 115A |

Weldable materials: Mild Steel, Stainless Steel, Aluminum (with optional Spool Gun)

Wire: solid core [0.025, 0.03, 0.035] in; flux cored [0.03, 0.035, 0.045] in; wire speed 50-500 IPM; spool Up to 12 lb spool

- [ ] This table matches page 7

### TIG

| Field | 120V | 240V |
|---|---|---|
| Current input at output | 20.6A at 125A | 15.6A at 175A |
| Welding current range | 10-125 A | 10-175 A |
| Rated duty cycles | 40% @ 125A; 100% @ 90A | 30% @ 175A; 100% @ 105A |

Weldable materials: Mild Steel, Stainless Steel, Chrome Moly

- [ ] This table matches page 7

### Stick

| Field | 120V | 240V |
|---|---|---|
| Current input at output | 19.5A at 80A | 23.7A at 175A |
| Welding current range | 10-80 A | 10-175 A |
| Rated duty cycles | 40% @ 80A; 100% @ 60A | 25% @ 175A; 100% @ 100A |

Weldable materials: Mild Steel, Stainless Steel

- [ ] This table matches page 7

Common: max OCV 86 VDC, 60 Hz input (all three tables).

- [ ] OCV and frequency match

## 2. Rating label (appears in the setup pictures, e.g. page 14)
This is the only place the 60% duty-cycle points appear. I read it at 1200 DPI. Open `knowledge/factcheck/rating-label-p14-14.png`, which shows the whole label zoomed in. Order on the label: MIG (torch icon), Stick (electrode holder icon), TIG (torch + rod icon).

| Voltage | Process | Range | Duty cycle points | Input current (I1max / I1eff) |
|---|---|---|---|---|
| 240V | MIG | 30A/15.5V to 220A/25V | 25% @ 200A (24V), 60% @ 130A (20.5V), 100% @ 115A (19.75V) | 25.5A / 12.8A |
| 240V | Stick | 10A/20.4V to 175A/27V | 25% @ 175A (27V), 60% @ 115A (24.6V), 100% @ 100A (24V) | 23.7A / 11.9A |
| 240V | TIG | 10A/10.4V to 175A/17V | 30% @ 175A (17V), 60% @ 125A (15V), 100% @ 105A (14.2V) | 15.6A / 8.5A |
| 120V | MIG | 30A/15.5V to 140A/21V | 40% @ 100A (19V), 60% @ 85A (18.25V), 100% @ 75A (17.75V) | 20.8A / 13.1A |
| 120V | Stick | 10A/20.4V to 80A/23.2V | 40% @ 80A (23.2V), 60% @ 70A (22.8V), 100% @ 60A (22.4V) | 19.5A / 12.3A |
| 120V | TIG | 10A/10.4V to 125A/15V | 40% @ 125A (15V), 60% @ 105A (14.2V), 100% @ 90A (13.6V) | 20.6A / 13A |

- [ ] Label values match the zoomed image (I already checked this once)

## 3. Controls (manual pages 8-9)
Open `knowledge/factcheck/page-08.png` and `page-09.png`. Check that each name exists and is spelled as printed. Positions are rough guesses and will be refined later.

### Front panel, page 8

- [ ] Home Button
- [ ] Back Button
- [ ] LCD Display
- [ ] Left Knob
- [ ] Control Knob
- [ ] Right Knob
- [ ] Storage Compartment
- [ ] Power Switch
- [ ] MIG Gun / Spool Gun Cable Socket
- [ ] Spool Gun Gas Outlet
- [ ] Negative Socket (-)
- [ ] Wire Feed Power Cable
- [ ] Positive Socket (+)

### Interior, page 9

- [ ] Cold Wire Feed Switch
- [ ] Feed Tensioner
- [ ] Wire Feed Mechanism
- [ ] Idler Arm
- [ ] Feed Roller Knob
- [ ] Wire Spool
- [ ] Spool Knob
- [ ] Wire Inlet Liner
- [ ] Foot Pedal Socket
- [ ] Wire Feed Control Socket

Front panel layout statement to check:
> Top: LCD display flanked by Home button (left) and Back button (right). Below the LCD: Left knob, Control knob (center, largest), Right knob; the left knob is marked with an A symbol (amps) and the right knob with a V symbol (volts). Below that: the VULCAN storage compartment door. Lower half: left compartment holds the MIG Gun/Spool Gun cable socket and the Power switch; the bottom row of sockets runs left to right: Spool Gun gas outlet, Negative (-) socket, Wire feed power cable, Positive (+) socket.

- [ ] Layout statement is correct

Interior layout statement to check:
> Wire compartment (side view). Left: Wire Spool on a Spool Knob. Wire runs through the Wire Inlet Liner to the Wire Feed Mechanism on the right (Feed Tensioner on top, Idler Arm, Feed Roller Knob). Cold Wire Feed Switch sits above the mechanism. Bottom: Foot Pedal Socket and Wire Feed Control Socket.

- [ ] Layout statement is correct

Open question: which page is which? I assumed Front Panel Controls is page 8 and Interior Controls is page 9. The text layer confirms: page 8 = Front Panel Controls, page 9 = Interior Controls.

## 4. The 8 facts that matter most (polarity and setup)
These are the facts the agent will be tested on. Verify each against the page.

- [ ] MIG, solid wire with gas (DCEP): ground clamp in Negative (-), wire feed power cable in Positive (+) — page 14, step 17a
- [ ] Flux-cored, gasless (DCEN): ground clamp in Positive (+), wire feed power cable in Negative (-) — page 13, step 16
- [ ] TIG: ground clamp in Positive (+), TIG torch cable in Negative (-) — page 24, steps 1-2
- [ ] Stick: ground clamp in Negative (-), electrode holder in Positive (+) — page 27, steps 1-2
- [ ] Feed tensioner: 3-5 for solid wire, 2-3 for flux-cored — page 15 note
- [ ] MIG gas flow 20-30 SCFH (page 20); TIG gas flow 10-25 SCFH (page 30); TIG uses 100% argon (page 25)
- [ ] Flux-cored porosity: check polarity, dirty workpiece/wire, CTWD (1/2 inch or less), travel speed; gas checks are MIG only — pages 37 and 43
- [ ] Duty cycle MIG 240V: 25% @ 200A = 2.5 min welding, 7.5 min rest — pages 7, 19, 23
