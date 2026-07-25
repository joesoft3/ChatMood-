// 🎞 Films — your storyboard films, live from the API (v0.5.0+).
//
// - Grid of films with hero-frame posters (extracted server-side via ffmpeg)
// - Live progress while a film is rendering (8s poll; resumes automatically)
// - Tap → fullscreen player (video_player), share link to clipboard,
//   delete / resume stuck renders — mirrors the web /films gallery.
import 'dart:async';
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:video_player/video_player.dart';

import 'api.dart';
import 'main.dart' show MoodColors;

class FilmsScreen extends StatefulWidget {
  const FilmsScreen({super.key});

  @override
  State<FilmsScreen> createState() => _FilmsScreenState();
}

class _FilmsScreenState extends State<FilmsScreen> {
  List<Map<String, dynamic>> _films = [];
  int _jobsRunning = 0;
  String? _error;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _refresh();
    _timer = Timer.periodic(const Duration(seconds: 8), (_) => _refresh(quiet: true));
  }

  Future<void> _refresh({bool quiet = false}) async {
    try {
      final res = await Api.get('/media/films');
      if (!mounted) return;
      setState(() {
        _films = ((res['films'] as List?) ?? []).cast<Map<String, dynamic>>();
        _jobsRunning = (res['jobs_running'] as num?)?.toInt() ?? 0;
        if (!quiet) _error = null;
      });
    } catch (e) {
      if (mounted && !quiet) setState(() => _error = '$e');
    }
  }

  bool _busy = false;

  Future<void> _filmFromPhoto() async {
    if (_busy) return;
    final r = await FilePicker.platform.pickFiles(type: FileType.image);
    final path = r?.files.single.path;
    final name = r?.files.single.name;
    if (path == null || name == null || !mounted) return;
    final ctrl = TextEditingController();
    final prompt = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: MoodColors.panel,
        title: const Text('🎬 Film from this photo'),
        content: TextField(
          controller: ctrl,
          maxLines: 3,
          autofocus: true,
          decoration: const InputDecoration(
              hintText: 'What should the film be about? e.g. a launch-day teaser for my waakye spot'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, ctrl.text.trim()), child: const Text('Render')),
        ],
      ),
    );
    if (prompt == null || prompt.length < 3) return;
    setState(() => _busy = true);
    try {
      final bytes = await File(path).readAsBytes();
      await Api.postMultipart('/media/videos/storyboard-i2v', bytes, name,
          fields: {'prompt': prompt});
      _refresh(quiet: true);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _delete(Map<String, dynamic> film) async {
    final prompt = (film['prompt'] as String?) ?? '';
    final yes = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: MoodColors.panel,
        title: const Text('Delete this film?'),
        content: Text(prompt.length > 90 ? '${prompt.substring(0, 90)}…' : prompt),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Delete')),
        ],
      ),
    );
    if (yes != true) return;
    try {
      await Api.delete('/media/films/${film['id']}');
      _refresh(quiet: true);
    } catch (e) {
      _toast('Delete failed: $e');
    }
  }

  Future<void> _resume(Map<String, dynamic> film) async {
    try {
      await Api.post('/media/films/${film['id']}/resume', const {});
      _toast('↻ Render relaunched');
      _refresh(quiet: true);
    } catch (e) {
      _toast('Resume failed: $e');
    }
  }

  Future<void> _share(Map<String, dynamic> film) async {
    final url = (film['url'] as String?) ?? '';
    if (url.isEmpty) return;
    await Clipboard.setData(ClipboardData(text: url));
    _toast('🔗 Film link copied (public, works ~24h)');
  }

  void _toast(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg), duration: const Duration(seconds: 2)));
  }

  void _play(Map<String, dynamic> film) {
    final url = (film['url'] as String?) ?? '';
    if (url.isEmpty) return;
    Navigator.of(context).push(MaterialPageRoute(builder: (_) => _PlayerScreen(film: film)));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: MoodColors.base,
      appBar: AppBar(
        backgroundColor: MoodColors.base,
        title: Row(
          children: [
            const Text('🎞 Films'),
            if (_films.any((f) => f['status'] == 'rendering')) ...[
              const SizedBox(width: 8),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: MoodColors.accent.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(20),
                ),
                child: const Text('⏺ rendering', style: TextStyle(fontSize: 11, color: MoodColors.accent)),
              ),
            ],
          ],
        ),
        actions: [
          IconButton(
            tooltip: 'Film from a photo',
            icon: const Icon(Icons.add_photo_alternate_outlined, size: 20),
            onPressed: _filmFromPhoto,
          ),
          
          IconButton(onPressed: _refresh, icon: const Icon(Icons.refresh, size: 20), tooltip: 'Refresh'),
        ],
      ),
      body: _error != null && _films.isEmpty
          ? Center(child: Padding(padding: const EdgeInsets.all(24), child: Text(_error!, textAlign: TextAlign.center)))
          : _films.isEmpty
              ? const Center(
                  child: Padding(
                    padding: EdgeInsets.all(24),
                    child: Text(
                      '🎬 No films yet.\nOpen the web app → Video Studio → pick "2-scene film" — it lands here when done.\n(Completion push included.)',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: Colors.grey),
                    ),
                  ),
                )
              : RefreshIndicator(
                  onRefresh: _refresh,
                  color: MoodColors.accent,
                  child: GridView.builder(
                    padding: const EdgeInsets.all(12),
                    gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                      crossAxisCount: 2,
                      mainAxisSpacing: 10,
                      crossAxisSpacing: 10,
                      childAspectRatio: 0.78,
                    ),
                    itemCount: _films.length,
                    itemBuilder: (_, i) => _FilmCard(
                      film: _films[i],
                      jobsRunning: _jobsRunning,
                      onPlay: () => _play(_films[i]),
                      onShare: () => _share(_films[i]),
                      onDelete: () => _delete(_films[i]),
                      onResume: () => _resume(_films[i]),
                    ),
                  ),
                ),
    );
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }
}

class _FilmCard extends StatelessWidget {
  const _FilmCard({required this.film, required this.jobsRunning, required this.onPlay, required this.onShare, required this.onDelete, required this.onResume});

  final Map<String, dynamic> film;
  final int jobsRunning;
  final VoidCallback onPlay;
  final VoidCallback onShare;
  final VoidCallback onDelete;
  final VoidCallback onResume;

  @override
  Widget build(BuildContext context) {
    final status = film['status'] as String? ?? '';
    final poster = film['poster'] as String? ?? '';
    final progress = (film['progress'] as num?)?.toInt() ?? 0;
    final count = (film['scene_count'] as num?)?.toInt() ?? 0;
    final audio = film['audio'] as String? ?? 'none';
    final prompt = film['prompt'] as String? ?? '';

    return Container(
      decoration: BoxDecoration(
        color: MoodColors.panel,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: Colors.white.withValues(alpha: 0.06)),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Expanded(
            child: status == 'rendering'
                ? Center(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const SizedBox(
                          width: 22,
                          height: 22,
                          child: CircularProgressIndicator(strokeWidth: 2, color: MoodColors.accent),
                        ),
                        const SizedBox(height: 8),
                        Text('Scene ${progress + 1 > count ? count : progress + 1}/$count', style: const TextStyle(fontSize: 11, color: Colors.grey)),
                      ],
                    ),
                  )
                : status == 'failed'
                    ? const Center(child: Text('🥀', style: TextStyle(fontSize: 28)))
                    : InkWell(
                        onTap: onPlay,
                        child: Stack(
                          fit: StackFit.expand,
                          children: [
                            if (poster.isNotEmpty)
                              Image.network(
                                poster,
                                fit: BoxFit.cover,
                                errorBuilder: (_, __, ___) => Container(color: Colors.black45),
                                loadingBuilder: (_, child, prog) =>
                                    prog == null ? child : Container(color: Colors.black45),
                              )
                            else
                              Container(color: Colors.black45),
                            const Center(
                              child: Icon(Icons.play_circle_fill, size: 44, color: Colors.white70),
                            ),
                          ],
                        ),
                      ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(8, 6, 8, 6),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(prompt, maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 11, color: Colors.white70)),
                const SizedBox(height: 4),
                Row(
                  children: [
                    Text('🎬 $count-scene', style: const TextStyle(fontSize: 10, color: Colors.grey)),
                    const SizedBox(width: 6),
                    if (audio != 'none') const Text('🔊', style: TextStyle(fontSize: 10)),
                    const Spacer(),
                    if (status == 'done') ...[
                      InkWell(onTap: onShare, child: const Padding(padding: EdgeInsets.all(4), child: Icon(Icons.link, size: 15, color: Colors.grey))),
                      InkWell(onTap: onDelete, child: const Padding(padding: EdgeInsets.all(4), child: Icon(Icons.delete_outline, size: 15, color: Colors.redAccent))),
                    ] else if (status == 'rendering' && jobsRunning == 0) ...[
                      InkWell(onTap: onResume, child: const Padding(padding: EdgeInsets.all(4), child: Icon(Icons.replay, size: 15, color: MoodColors.accent))),
                      InkWell(onTap: onDelete, child: const Padding(padding: EdgeInsets.all(4), child: Icon(Icons.delete_outline, size: 15, color: Colors.redAccent))),
                    ] else ...[
                      InkWell(onTap: onDelete, child: const Padding(padding: EdgeInsets.all(4), child: Icon(Icons.delete_outline, size: 15, color: Colors.redAccent))),
                    ],
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _PlayerScreen extends StatefulWidget {
  const _PlayerScreen({required this.film});

  final Map<String, dynamic> film;

  @override
  State<_PlayerScreen> createState() => _PlayerScreenState();
}

final Map<String, Duration> _playbackPositions = {};

class _PlayerScreenState extends State<_PlayerScreen> {
  late final VideoPlayerController _c;
  bool _ready = false;
  bool _failed = false;
  Duration _position = Duration.zero;
  Duration _duration = Duration.zero;

  @override
  void initState() {
    super.initState();
    final filmId = widget.film['id'] as String? ?? '';
    _c = VideoPlayerController.networkUrl(Uri.parse(widget.film['url'] as String? ?? ''))
      ..initialize().then((_) {
        if (!mounted) return;
        final saved = _playbackPositions[filmId] ?? Duration.zero;
        if (saved > Duration.zero && saved < _c.value.duration) {
          _c.seekTo(saved);
        }
        setState(() {
          _ready = true;
          _duration = _c.value.duration;
        });
        _c.play();
        _c.addListener(_onVideoUpdate);
      }).catchError((_) {
        if (mounted) setState(() => _failed = true);
      });
  }

  String _formatDuration(Duration d) {
    String twoDigits(int n) => n.toString().padLeft(2, '0');
    final min = twoDigits(d.inMinutes.remainder(60));
    final sec = twoDigits(d.inSeconds.remainder(60));
    return '$min:$sec';
  }

  void _onVideoUpdate() {
    if (!mounted) return;
    final filmId = widget.film['id'] as String? ?? '';
    _position = _c.value.position;
    _duration = _c.value.duration;
    if (_position.inMilliseconds > 500) {
      _playbackPositions[filmId] = _position;
    }
    if (_ready) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final prompt = widget.film['prompt'] as String? ?? '';
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(backgroundColor: Colors.black, title: Text(prompt, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 13))),
      body: Center(
        child: _failed
            ? const Text('Playback failed — the link may have expired.', style: TextStyle(color: Colors.grey))
            : !_ready
                ? const CircularProgressIndicator(color: MoodColors.accent)
                : Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Expanded(
                        child: GestureDetector(
                          onTap: () => setState(() => _c.value.isPlaying ? _c.pause() : _c.play()),
                          child: AspectRatio(aspectRatio: _c.value.aspectRatio, child: VideoPlayer(_c)),
                        ),
                      ),
                      if (_duration.inMilliseconds > 0)
                        Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                          child: Row(
                            children: [
                              Text(_formatDuration(_position), style: const TextStyle(fontSize: 10, color: Colors.grey)),
                              Expanded(
                                child: Slider(
                                  value: _position.inMilliseconds.toDouble(),
                                  min: 0,
                                  max: _duration.inMilliseconds.toDouble(),
                                  onChanged: (v) => _c.seekTo(Duration(milliseconds: v.toInt())),
                                ),
                              ),
                              Text(_formatDuration(_duration), style: const TextStyle(fontSize: 10, color: Colors.grey)),
                            ],
                          ),
                        ),
                    ],
                  ),
      ),
      floatingActionButtonLocation: FloatingActionButtonLocation.centerFloat,
      floatingActionButton: _ready && !_failed
          ? Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                FloatingActionButton.small(
                  backgroundColor: MoodColors.accent,
                  heroTag: 'play_pause',
                  onPressed: () => setState(() => _c.value.isPlaying ? _c.pause() : _c.play()),
                  child: Icon(_c.value.isPlaying ? Icons.pause : Icons.play_arrow, color: Colors.black),
                ),
                const SizedBox(width: 12),
                FloatingActionButton.small(
                  backgroundColor: MoodColors.panel,
                  heroTag: 'share',
                  onPressed: () {
                    final url = widget.film['url'] as String? ?? '';
                    if (url.isNotEmpty) {
                      Clipboard.setData(ClipboardData(text: url));
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(content: Text('🔗 Film link copied'), duration: Duration(seconds: 2)),
                      );
                    }
                  },
                  child: const Icon(Icons.link, size: 18, color: Colors.white70),
                ),
              ],
            )
          : null,
    );
  }

  @override
  void dispose() {
    _c.removeListener(_onVideoUpdate);
    _c.dispose();
    super.dispose();
  }
}
