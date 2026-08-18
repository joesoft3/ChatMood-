# 📲 Mobile — Films screen & playback

The Flutter app (`mobile/lib/films_screen.dart`) mirrors the web `/films` gallery and supports the full film lifecycle: render, poll, play, share, delete, resume.

## Chat finish (web parity)

The chat screen (`mobile/lib/chat_screen.dart`) now matches the web finish pass:

| Feature | How it works | API |
|---|---|---|
| ✏️ Edit & resend | Tap **Edit** on your bubble, change the text, **Save & resend**. The client truncates the thread locally and posts `edit_from` on `/chat/stream` so the server rewinds that turn. Hidden in team workspaces (owner-only). | `POST /chat/stream` `{edit_from}` |
| 📌 Pin / delete | Drawer pin keeps a personal chat above recency; unpin restores order. Delete confirms, then `DELETE`s the conversation. | `PATCH /conversations/{id}` `{pinned}` · `DELETE /conversations/{id}` |
| 💬 Follow-ups | After a text answer, up to three tap-to-send chips land above the composer. | SSE `suggestions` |
| ⬇✏️🗑 Media | Live and restored generations carry `file_id`. Download shares via the stable `/files/{id}/download` route; Edit prefills the composer; Delete removes the library row and the card. | `GET/DELETE /files/{id}` |

## Navigation

Drawer → **🎞 Films** opens `FilmsScreen`. It reads from `GET /media/films` every 8 s (`Timer.periodic`) and updates the grid live.

## Key actions

| Feature | Mobile implementation | API endpoint |
|---|---|---|
| Film from photo | `FilePicker` → multipart `POST /media/videos/storyboard-i2v` with image bytes + prompt | `storyboard-i2v` |
| Play finished film | `VideoPlayerController.networkUrl` streams `/media/files/{name}` | `GET /media/files/{name}` |
| Live render progress | Grid shows `Scene N/M` with a spinner; `jobsRunning` badge in AppBar | `GET /media/films` (`status=rendering`) |
| Resume stuck film | `POST /media/films/{id}/resume` → toast confirmation | `resume_film` |
| Share public link | `Clipboard.setData` with the film's `url` | `GET /media/public/films/{fid}` |
| Delete film | Alert dialog → `DELETE /media/films/{id}` → refresh | `delete_film` |

## Player screen (`_PlayerScreen`)

- Fullscreen black background.
- Poster / video plays with `AspectRatio` matching the controller.
- Tap toggles play/pause.
- If initialization fails (`catchError`), shows a grey "Playback failed" message.

## Design details

- Grid: 2 columns (`crossAxisCount: 2`), `childAspectRatio: 0.78`, 12 px padding.
- Card: rounded 14 px, dark panel color, white 6% border.
- Rendering card: centered spinner + scene progress text.
- Failed card: emoji `🥀`.
- Done card: poster image (`Image.network`) with a play overlay (`Icons.play_circle_fill`).
- Audio chip (`🔊`) shown when `audio != 'none'`.
- Buttons (share, delete, resume, refresh) use `InkWell` with 4 px padding.

## Error handling

- Empty list shows a centered hint message explaining how to create a film via the web studio.
- Network errors show in a `SnackBar` or centered text when the grid is empty.
- `_busy` flag prevents concurrent uploads for the photo-to-film flow.
