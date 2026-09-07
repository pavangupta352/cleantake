---
name: CleanTake
description: A clear, source-traceable workspace for reviewing recorded dialogue repairs.
colors:
  desk: "#eef1f5"
  paper: "#ffffff"
  chrome: "#f9fafc"
  ink: "#20314b"
  secondary: "#586980"
  blue: "#244f99"
  blue-hover: "#173d80"
  blue-active: "#12336b"
  teal: "#28756a"
  amber: "#795717"
  amber-paper: "#fbf0d9"
  line: "#d8dfe8"
  line-strong: "#b9c5d5"
  focus: "#6084c3"
  neutral-hover: "#e7edf7"
  neutral-active: "#d9e4f4"
  quiet-hover: "#e1e7f0"
  selected-row: "#e5edf9"
  good-ink: "#2b6253"
  good-paper: "#e0eee8"
  muted-ink: "#566579"
  muted-paper: "#e9edf2"
  source-blue: "#3459a2"
  source-teal: "#277b74"
  source-plum: "#88628d"
  source-ochre: "#9a6936"
typography:
  title:
    fontFamily: '"Segoe UI", "Helvetica Neue", "Arial", sans-serif'
    fontSize: "16px"
    fontWeight: 650
    lineHeight: 1.3
    letterSpacing: "-0.015em"
  title-small:
    fontFamily: '"Segoe UI", "Helvetica Neue", "Arial", sans-serif'
    fontSize: "15px"
    fontWeight: 650
    lineHeight: 1.35
  body:
    fontFamily: '"Segoe UI", "Helvetica Neue", "Arial", sans-serif'
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: '"Segoe UI", "Helvetica Neue", "Arial", sans-serif'
    fontSize: "12px"
    lineHeight: 1.5
  button:
    fontFamily: '"Segoe UI", "Helvetica Neue", "Arial", sans-serif'
    fontSize: "14px"
    fontWeight: 550
    lineHeight: 1.3
  time:
    fontFamily: '"Segoe UI", "Helvetica Neue", "Arial", sans-serif'
    fontSize: "18px"
    fontWeight: 600
    lineHeight: 1.5
    letterSpacing: "-0.02em"
  keyboard:
    fontFamily: 'ui-monospace, "SFMono-Regular", monospace'
    fontSize: "12px"
    lineHeight: 1.5
rounded:
  tag: "3px"
  field: "4px"
  control: "5px"
  form: "6px"
  dialog: "8px"
spacing:
  tight: "4px"
  label: "6px"
  control: "8px"
  field-pair: "10px"
  compact: "12px"
  standard: "16px"
  section: "20px"
  desk: "25px"
components:
  button-primary:
    backgroundColor: "{colors.blue}"
    textColor: "{colors.paper}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "7px 12px"
  button-primary-hover:
    backgroundColor: "{colors.blue-hover}"
    textColor: "{colors.paper}"
  button-primary-active:
    backgroundColor: "{colors.blue-active}"
    textColor: "{colors.paper}"
  button-secondary:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "7px 12px"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "7px 12px"
  field:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.field}"
    padding: "9px 10px"
  state-good:
    backgroundColor: "{colors.good-paper}"
    textColor: "{colors.good-ink}"
    rounded: "{rounded.tag}"
    padding: "3px 7px"
  state-warning:
    backgroundColor: "{colors.amber-paper}"
    textColor: "{colors.amber}"
    rounded: "{rounded.tag}"
    padding: "3px 7px"
  state-muted:
    backgroundColor: "{colors.muted-paper}"
    textColor: "{colors.muted-ink}"
    rounded: "{rounded.tag}"
    padding: "3px 7px"
  score:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.control}"
  inspector:
    backgroundColor: "{colors.chrome}"
    rounded: "{rounded.control}"
  repair-row-selected:
    backgroundColor: "{colors.selected-row}"
    textColor: "{colors.ink}"
    padding: "11px 14px"
---

# Design System: CleanTake

## Overview

**Creative North Star: "Annotated performance score"**

CleanTake places recorded audio on a light slate editing desk. White waveform lanes, deep blue text and compact controls make the performance the working surface. Shared time, readable source names and explicit repair states carry the visual identity.

The interface is calm and dense enough for repeated listening. Borders and modest tonal changes separate persistent regions; stronger color marks an action, a selection or evidence that needs attention. Labels explain what the editor can hear and change. Artwork, decorative meters and promotional claims do not substitute for recorded evidence.

**Key Characteristics:**
- Light slate desk with white waveform lanes and quiet control surfaces.
- One blue action accent, with separate source identity and repair status colors.
- Compact sans serif text, tabular time values and explicit units.
- Shared timeline coordinates, a contextual inspector and an anchored transport.
- Visible focus, labeled states and numeric alternatives to waveform seeking.

## Colors

The palette combines cool working neutrals with restrained blue actions, muted recording colors and warm uncertainty. The frontmatter records the implemented values; the central CSS properties live in `studio/src/tokens.css`, with component treatments in `studio/src/styles.css` and the ordered source palette in `studio/src/App.tsx`.

### Primary

- **Action blue** (`blue`): primary actions, playback, active audition controls, selected queue filters, links and interface icons. Its deeper hover and active treatments preserve a clear button silhouette.
- **Focus blue** (`focus`): the visible keyboard outline; it remains distinct from the thin selection boundaries on the timeline.

### Secondary

- **Uncertainty amber** (`amber`, `amber-paper`): proposals, unresolved repairs, alignment warnings and explanatory caution. Warm paper supports readable text without turning the workspace into an alert wall.
- **Confirmation green** (`good-ink`, `good-paper`): accepted repair and usable alignment badges. The teal primitive also appears in local-processing guidance.
- **Recording colors** (`source-blue`, `source-teal`, `source-plum`, `source-ochre`): four source slots, assigned in project source order. Each color appears in its source dot and waveform. These colors do not denote microphone type, speaker identity, quality or confidence.

### Neutral

- **Slate desk** (`desk`): the surrounding working area.
- **White paper** (`paper`): audio evidence, fields, ordinary buttons and repair rows.
- **Quiet chrome** (`chrome`): project bar, source labels, inspector and transport.
- **Blue ink** (`ink`) and **secondary slate** (`secondary`): primary reading hierarchy and supporting facts.
- **Fine line** (`line`) and **control line** (`line-strong`): surface divisions and field/button boundaries.
- **Selected row** (`selected-row`): the current repair, independent of whether it is accepted, rejected or awaiting review.
- **Muted status** (`muted-ink`, `muted-paper`): rejected repairs, which remain legible and inspectable.

**The Separate Meanings Rule.** Source identity, selection and repair status are separate visual channels. Keep a written source name and state label beside their color treatment. Accepted spans use a common green annotation carrying the donor's name; they do not recolor the entire output lane to the donor hue.

## Typography

**Interface Font:** Segoe UI, with Helvetica Neue, Arial and sans serif fallbacks. The same stack serves headings, fields and data; there is no separate display face.

**Keyboard/Code Font:** the platform monospace stack. Timecodes use the interface font with tabular numerals, rather than changing to a code face.

The type ramp is compact and task-specific rather than a large promotional hierarchy. Section titles use the `title` and `title-small` roles. The studio heading is slightly larger (23px), reducing to 21px and then 20px at narrow widths. The project shelf uses a larger introductory heading, confined to that entry surface.

Body text uses the `body` role. Most supporting copy and control labels sit at 12–13px; small timestamps, source metadata and legends use 10–11px. These small annotations support the main labels, rather than replacing them. The selected passage's time range is more prominent (21px desktop, 22px in the single-column inspector). The transport time follows the `time` role and steps down to 16px and 15px on narrower layouts.

The native launch surface uses the same interface font, with a single product name (30px, weight 650, line height 1.25, letter spacing −0.02em) and a secondary status line (14px, line height 1.5). This brief startup hierarchy does not change the studio's compact type ramp.

**The Time Is Data Rule.** Use tabular numerals for timecodes, repair ranges, durations and numeric metadata. Keep seconds, milliseconds, decibels and alignment units visible in labels. Use sentence case; status badges capitalize their state text.

## Layout

The studio is centered within a maximum width of 1800px. Its desktop inset is 25px, with a 62px project bar above and a fixed transport of at least 80px below. The main grid gives the timeline the flexible column and the inspector a 304px column, separated by 20px. The repair queue continues under the score. The inspector is part of document flow; the transport stays attached to the viewport.

The waveform score uses a consistent label column (187px at the base desktop size). The ruler and every audio lane share the same remaining width. Ruler tick anchors are placed at the exact endpoints and quarter points of that width; only endpoint label text shifts inward. Lane borders, playhead lines, selection bands and source-span annotations use this same coordinate system. Base source lanes are at least 104px tall; the output lane is at least 114px.

Spacing is practical rather than a rigid mathematical scale: 4–8px within tight control groups, 10px between paired fields, 12–20px for local padding and related sections, and 25px at the desktop workspace edge. Maintain this distinction between dense controls and breathing room around tasks.

| Width condition | Implemented behavior |
| --- | --- |
| At least 1600px | Inspector grows to 330px, grid gap to 26px, lane and waveform minimum height to 120px. |
| At most 1190px | Inspector becomes 280px, gap 16px and label column 168px; secondary transport hints and saved-state text recede. |
| At most 960px | Inspector becomes 258px, gap 12px and label column 143px; desk inset is 17px and transport wraps. |
| At most 760px | One main column places the inspector below the queue; introductory and empty-state layouts also stack. |
| At most 500px | Desk inset is 12px, label column 123px, bar height 57px and waveform minimum height 94px. The ruler keeps the two endpoints and midpoint. The transport reserves at least 151px and places audition controls on their own row. |

The page supports widths from 320px. Bottom padding grows with the transport (112px desktop, 150px at the 960px breakpoint, 185px at the 500px breakpoint), allowing lower controls to scroll above it. Long source names truncate in lanes and rows; the source settings and replacement selector retain the underlying name. Paired numeric fields remain available on narrow screens.

**The Shared Clock Rule.** Aligned lanes share the displayed time range and playhead. An uncertain source explicitly says “Own clock · alignment needed,” dims its waveform and withholds project-time seeking and selection overlays until aligned.

The desktop edition places this same responsive studio inside an ordinary framed OS window. Valid saved bounds and the maximized state are restored; bounds that no longer fit a display fall back to a centered window, capped at 1440 × 960px with room around the available work area. The normal minimum is 760 × 560px, reduced when the available window bounds are smaller. The shell adds no custom titlebar or second editing layout.

## Elevation & Depth

Persistent editing surfaces are flat, separated by fine borders and light background changes. There is no ambient shadow beneath the score or inspector. Small shadows belong to the selected audition segment, while larger shadows identify temporary drawers and confirmation dialogs.

### Shadow Vocabulary

- **Selected audition segment** (`0 1px 3px #1c335119`): slight lift for the pressed mode inside its recessed group.
- **Side drawer** (`-10px 0 35px #27344a20`): distinguishes transcript, export and help content from the underlying editor.
- **Confirmation dialog** (`0 12px 60px #18233340`): emphasizes a temporary decision, supported by a translucent backdrop (`#20304970`).

## Shapes

Controls and containers use small rounded rectangles. Tags and inner segmented buttons use `tag`; fields and notices use `field`; standard buttons, score and inspector use `control`. The project creation form uses `form`, and dialogs use `dialog`. Full-width list rows, waveform interaction areas and accepted-span strips keep square adjoining edges.

Source dots are small circles (7px) and the playhead is a one-pixel vertical line with a small square cap. These are data markers, not a general invitation to use pill-shaped containers. Borders are ordinarily one pixel; the active queue filter uses a two-pixel underline.

## Components

### Buttons

Compact, explicit actions with a stable silhouette. Standard buttons have a minimum height of 36px, the `control` radius and the padding recorded in frontmatter. Primary buttons use action blue on white text; secondary buttons use white paper with a control-line border. Quiet and icon buttons remove the resting border and fill, adding a pale background on hover. Text actions use blue text and a smaller footprint. Destructive actions use red in their dedicated confirmation or project settings context.

Background, border and text colors transition over 160ms with `ease-out`. Pressed states deepen the fill without moving the control. Disabled buttons use reduced opacity (0.48) and remain visibly unavailable. Keyboard focus uses a three-pixel blue outline with a three-pixel offset. Icon buttons retain an accessible action name even where narrow layouts hide neighboring text.

### Inputs / Fields

White fields with a control-line border, `field` radius and visible labels above. Labels use a six-pixel gap; paired fields use two equal columns with a ten-pixel gap. Numeric repair fields state Start/End in seconds, Gain in dB and Crossfade in ms. The transport includes a separate “Go to (s)” field. Field focus inherits the global outline; disabled fields reduce opacity to 0.6. Errors appear as actionable messages with text, rather than relying on a red input border alone.

### Navigation and Filters

The slim project bar holds project switching, undo/redo and the transcript/export/help actions. Brand and project controls return to the shelf. The bar becomes more compact on small screens; the full wordmark is hidden in the narrow editing view while its accessible name remains.

Repair filters are a horizontal button group. Blue text, stronger weight and an underline mark the pressed filter; counts are small inset tags. Filtering and row selection are distinct states. The audition group uses a recessed rounded container with a white, lightly lifted pressed segment and explicit Original, Repair and Source labels.

### Status Tags and Messages

Small rectangular tags pair state text with color. Accepted, aligned, manual and reference states use confirmation green; rejected uses muted gray; proposals and unresolved states use amber. An accepted badge describes an editor decision, not a guarantee of listening quality. Job progress has a blue-tinted strip and status text; errors have a warm red strip with an available recovery or dismissal action. Status and error announcements use live regions.

### Score and Source Lanes

The score is one continuous white container, divided into toolbar, ruler, output, source lanes and a compact legend. Waveforms are drawn from actual audio peak data. Each source label combines its name, colored dot and alignment or recording metadata. Coverage gaps are shaded. Selection is a pale blue vertical band with two boundaries; the playhead stays visible above it. Accepted repairs place a thin, clickable donor-name annotation along the output lane's lower edge.

Selecting a repair focuses a contextual time window and the same selected range across aligned lanes. The source inspector exposes the replacement and numerical edit controls. Accepted-span buttons open the corresponding repair. The pointer waveform area seeks; keyboard users have the numeric seek field and labeled timeline controls. Loading and retry states are textually explicit, with no fabricated waveform placeholder.

### Repair Rows and Inspector

Repair rows form a continuous list with shared column alignment and bottom dividers. Time, duration, damage description, donor name and status make each row scannable. The selected row uses a pale blue fill while keeping its independent status badge.

The right inspector uses quiet chrome, a bordered heading and stacked content. It holds one selected passage, source settings or introductory guidance at a time. Edit boundaries, donor selection, gain, crossfade, save and decision actions remain grouped with the passage. The layout stacks below the score on small screens, retaining source and numeric detail.

### Transport, Drawers and Motion

Playback stays visible at the bottom with the current time, audition mode, donor selector and numeric seeking. Switching audition mode preserves the playhead position and resumes only when playback was active. The loading spinner is functional feedback (1.4 seconds per linear rotation). There are no entrance animations.

Export, transcript and help use a right-side drawer (420px wide, capped at the viewport width) between the project bar and transport. Confirmation dialogs use a centered, padded surface with a maximum width of 500px. Reduced-motion settings reduce transitions and animations to 0.01ms, run animations once and use immediate scrolling.

### Native Desktop Shell

The shell retains OS window controls and application menus around the existing studio. Its initial background is quiet chrome. The centered launch surface has 40px of padding, a blue waveform mark (48px), the product name and “Opening your studio…” in secondary slate. It uses a busy state and a status announcement, with no progress percentage or decorative animation. The window becomes visible after its first rendered state; the ready studio then replaces the launch surface.

Native Edit → Undo and Redo use the studio's project history when focus is outside a text-entry control. In text-entry controls they preserve native text undo/redo, and an open modal prevents a project-history action behind it. Menu accelerators share this routing: Command/Ctrl+Z for Undo and Command/Ctrl+Shift+Z for Redo, with Ctrl+Y also registered outside macOS. Cut, Copy, Paste and Select All remain native text actions. View provides studio reload, zoom and fullscreen; Help provides the editing guide, downloads, problem reporting, licenses and log access.

Startup and service failures use a native error dialog with “Try again,” “Show log” and “Quit.” Retry returns to the launch state while reopening the studio; log access opens its folder. Closing the last window quits the application and stops its local service. Opening another instance focuses the existing window. Saved project decisions remain available on restart.

Prepared exports use the OS save dialog, titled “Save CleanTake export,” with the generated filename in Downloads as its initial destination. The studio keeps responsibility for preparing the audio or archive; the native dialog lets the editor choose where to save it. Native dialogs and menus inherit the platform's presentation rather than imitating studio controls.

## Do's and Don'ts

### Do:

- **Do** keep audio evidence on a shared white score with visible time and source labels.
- **Do** distinguish source identity, selection and repair status with separate treatments and written labels.
- **Do** retain the numeric seek and repair fields alongside pointer waveform actions.
- **Do** show uncertain alignment and missing coverage before a source can be treated as synchronized evidence.
- **Do** preserve compact controls, fine dividers and modest tonal depth on persistent editing surfaces.
- **Do** retain visible keyboard focus, explicit units and reduced-motion behavior.

### Don't:

- **Don't** replace source waveforms with decorative audio marks or invented meter readings.
- **Don't** imply that a source hue measures confidence, or that an accepted badge certifies audio quality.
- **Don't** move ruler ticks independently of waveform coordinates to make their labels fit.
- **Don't** turn the working score into a grid of oversized summary cards.
- **Don't** omit real source names or state text because a colored indicator is present.
- **Don't** introduce ornamental motion into passage selection or playback controls.
