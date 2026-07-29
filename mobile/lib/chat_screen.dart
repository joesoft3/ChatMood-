import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:audioplayers/audioplayers.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';
import 'package:video_player/video_player.dart';

import 'design_screen.dart';
import 'edit_screen.dart';
import 'orders_screen.dart';
import 'films_screen.dart';
import 'tasks_screen.dart';

import 'api.dart';
import 'arena_view.dart';
import 'login_screen.dart';
import 'main.dart';

const Color lightBase = Color(0xFFF8F9FA);
const Color lightPanel = Colors.white;
const Color lightLine = Color(0xFFE5E7EB);
const Color lightAccent = Color(0xFF3F82F6);

class AgentStep {
  AgentStep({required this.agent, required this.task, this.status = 'queued', this.preview});
  final String agent;
  final String task;
  String status; // queued | running | done
  String? preview;
}

/// 🎨🎬 In-chat creation (v1.9.7): image/video generated inline from the chat box.
class ChatMedia {
  ChatMedia({
    required this.kind,
    this.url,
    this.prompt,
    this.stored,
    this.pending = false,
    this.stage,
    this.done,
    this.total,
  });

  final String kind; // 'image' | 'video'
  String? url;
  String? prompt;
  String? stored; // r2 | local | hotlink
  bool pending;
  String? stage; // scenes | compositing
  int? done;
  int? total;

  /// Reload contract: assistant meta.media[0] re-renders the artifact.
  static ChatMedia? fromMeta(dynamic meta) {
    if (meta is! Map) return null;
    final list = meta['media'];
    if (list is! List || list.isEmpty || list.first is! Map) return null;
    final m = Map<dynamic, dynamic>.from(list.first as Map);
    return ChatMedia(
      kind: '${m['kind'] ?? 'image'}',
      url: m['url'] as String?,
      prompt: m['prompt'] as String?,
      stored: m['stored'] as String?,
    );
  }
}

class ChatMsg {
  ChatMsg({required this.role, required this.text, this.author});
  final String role; // 'user' | 'assistant'
  String text;
  String? author; // display label for user messages in team workspaces
  List<AgentStep>? steps;
  ArenaLiveState? arenaLive; // ⚔️ while the arena streams
  ArenaVerdict? arenaData; // ⚔️ final verdict (live or restored from meta)
  String? think; // 🧠 extended reasoning line
  ChatMedia? media; // 🎨🎬 in-chat creation
}

class Conversation {
  Conversation({required this.id, required this.title});
  final String id;
  final String title;
}

class Workspace {
  Workspace({required this.id, required this.name, this.owner = false});
  final String id;
  final String name;
  final bool owner;
}

class AttachedFile {
  AttachedFile({required this.id, required this.filename});
  final String id;
  final String filename;
}

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> with WidgetsBindingObserver {
  final _input = TextEditingController();
  final _scroll = ScrollController();
  final List<ChatMsg> _messages = [];
  final List<AttachedFile> _files = [];
  final _recorder = AudioRecorder();
  final _player = AudioPlayer();
  int _homeTab = 0; // 🏠 Grok-style home: 0 = Ask (chat), Imagine → creation studios
  List<Conversation> _conversations = [];
  String? _conversationId;
  String? _recordPath;
  bool _busy = false;
  bool _search = true;
  bool _agentMode = false;
  bool _arenaMode = false;
  bool _thinkOn = false;
  String _model = 'auto';
  bool _recording = false;
  // 🏠 idle auto-home (web parity): 5 min without activity → back to the clean
  // Grok home. Chats are never lost — they live in the ☰ drawer history.
  static const Duration _idleReset = Duration(minutes: 5);
  DateTime _lastActive = DateTime.now();
  Timer? _idleTimer;
  // ---- teams
  List<Workspace> _workspaces = [];
  Workspace? _workspace; // null = personal chats
  Map<String, String> _authors = {}; // user_id → display label (team conversations)
  String _userName = 'Creator';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _idleTimer = Timer.periodic(const Duration(minutes: 1), (_) => _checkIdle());
    _loadConversations();
    _loadWorkspaces();
    _loadProfile();
  }

  Future<void> _loadProfile() async {
    try {
      final data = await Api.get('/auth/me');
      if (data is Map) {
        final email = data['email'] as String?;
        if (email != null && email.isNotEmpty) {
          setState(() {
            _userName = email.split('@').first;
            if (_userName.isNotEmpty) {
              _userName = _userName[0].toUpperCase() + _userName.substring(1);
            }
          });
        }
      }
    } catch (_) {}
  }

  @override
  void dispose() {
    _idleTimer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    _recorder.dispose();
    _player.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _checkIdle(); // stale background app snaps home
  }

  void _poke() {
    _lastActive = DateTime.now();
  }

  void _checkIdle() {
    if (!mounted) return;
    if (_busy || _recording) return; // NEVER chop a live stream or a recording
    if (DateTime.now().difference(_lastActive) >= _idleReset) {
      _poke();
      _goHomeIdle();
    }
  }

  /// Idle reset: back to the clean home from any state — without deleting anything.
  void _goHomeIdle() {
    if (_conversationId == null && _messages.isEmpty && _files.isEmpty) return;
    setState(() {
      _conversationId = null;
      _messages.clear();
      _files.clear();
    });
    _loadConversations(); // keep the drawer instantly current
  }

  Future<void> _loadConversations() async {
    try {
      if (_workspace == null) {
        final data = await Api.get('/conversations');
        setState(() {
          _conversations = [
            for (final c in (data as List)) Conversation(id: c['id'] as String, title: c['title'] as String),
          ];
        });
      } else {
        final data = await Api.get('/workspaces/${_workspace!.id}/conversations');
        setState(() {
          _conversations = [
            for (final c in (data['conversations'] as List))
              Conversation(id: c['id'] as String, title: '${c['author']}: ${c['title']}'),
          ];
          _authors = {
            for (final e in (data['authors'] as Map).entries) '${e.key}': '${e.value}',
          };
        });
      }
    } catch (_) {/* api down — drawer just stays empty */}
  }

  // ------------------------------------------------------------------ teams
  Future<void> _loadWorkspaces() async {
    try {
      final data = await Api.get('/workspaces');
      setState(() {
        _workspaces = [
          for (final w in (data['workspaces'] as List))
            Workspace(id: w['id'] as String, name: w['name'] as String, owner: w['owner'] as bool? ?? false),
        ];
      });
    } catch (_) {/* teams unavailable — drawer hides the section */}
  }

  void _selectWorkspace(Workspace? w) {
    Navigator.of(context).maybePop();
    setState(() {
      _workspace = w;
      _conversationId = null;
      _messages.clear();
      _files.clear();
      _authors = {};
    });
    _loadConversations();
  }

  Future<void> _joinInvite() async {
    final ctrl = TextEditingController();
    String? err;
    final joined = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDlg) => AlertDialog(
          backgroundColor: lightPanel,
          title: const Text('Join a team'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: ctrl,
                decoration: const InputDecoration(hintText: 'Paste invite link or code'),
              ),
              if (err != null)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(err!, style: const TextStyle(color: Colors.redAccent, fontSize: 12)),
                ),
            ],
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
            FilledButton(
              style: FilledButton.styleFrom(backgroundColor: MoodColors.accent, foregroundColor: Colors.black),
              onPressed: () async {
                var t = ctrl.text.trim();
                final m = RegExp(r'/join/([A-Za-z0-9_\-]+)').firstMatch(t);
                if (m != null) t = m.group(1)!;
                if (t.length < 8) {
                  setDlg(() => err = 'That does not look like an invite code.');
                  return;
                }
                try {
                  final res = await Api.post('/workspaces/join', {'token': t});
                  if (ctx.mounted) Navigator.pop(ctx, true);
                  final wsName = (res['workspace']?['name'] as String?) ?? 'workspace';
                  _toast(res['already_member'] == true ? 'Already a member' : 'Joined $wsName 🎉');
                } catch (e) {
                  setDlg(() => err = e.toString().replaceFirst('Exception: ', ''));
                }
              },
              child: const Text('Join'),
            ),
          ],
        ),
      ),
    );
    if (joined == true) _loadWorkspaces();
  }

  Future<void> _openConversation(String id) async {
    Navigator.of(context).maybePop(); // close the drawer
    setState(() {
      _conversationId = id;
      _messages.clear();
      _busy = true;
    });
    try {
      final data = await Api.get('/conversations/$id');
      if (data['authors'] is Map) {
        _authors = {
          for (final e in (data['authors'] as Map).entries) '${e.key}': '${e.value}',
        };
      }
      setState(() {
        _messages
          ..clear()
          ..addAll([
            for (final m in (data['messages'] as List))
              if (m['role'] == 'user' || m['role'] == 'assistant')
                ChatMsg(
                  role: m['role'] as String,
                  text: m['content'] as String,
                  author: (m['role'] == 'user' && _workspace != null && m['user_id'] != null)
                      ? _authors['${m['user_id']}']
                      : null,
                )
                  // ⚔️ restore arena verdicts + 🧠 thinking lines + 🎨🎬 creations from persisted meta
                  ..arenaData = (m['meta'] is Map && (m['meta'] as Map)['mode'] == 'arena')
                      ? ArenaVerdict.fromMeta(m['meta'] as Map)
                      : null
                  ..think = _thinkLine(m['meta'])
                  ..media = ChatMedia.fromMeta(m['meta']),
          ]);
      });
      _scrollToBottom();
    } catch (_) {/* ignore */} finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _newChat() {
    Navigator.of(context).maybePop();
    setState(() {
      _conversationId = null;
      _messages.clear();
      _files.clear();
    });
  }

  /// Home starter actions type into the composer rather than sending instantly.
  /// Keep the caret at the end so the next character the user types continues
  /// the suggested prompt.
  void _prefill(String text) {
    setState(() {
      _input.text = text;
      _input.selection = TextSelection.collapsed(offset: text.length);
    });
  }

  Future<void> _send() async {
    final text = _input.text.trim();
    if ((text.isEmpty && _files.isEmpty) || _busy) return;
    _input.clear();
    await _sendMessage(text);
  }

  /// Core send path — also reused by ⚔️ rematch (replays the last question).
  Future<void> _sendMessage(String text, {bool rematch = false}) async {
    if (text.isEmpty || _busy) return;
    _poke();
    final useArena = _arenaMode || rematch;
    final fileIds = rematch ? <String>[] : _files.map((f) => f.id).toList();
    final assistant = ChatMsg(role: 'assistant', text: '');
    setState(() {
      _busy = true;
      _messages.add(ChatMsg(role: 'user', text: text));
      _messages.add(assistant);
      if (!rematch) _files.clear();
    });
    _scrollToBottom();
    final payload = {
      'conversation_id': _conversationId,
      'message': text,
      'files': _agentMode ? <String>[] : fileIds,
      'search': _search,
      'workspace_id': _workspace?.id, // personal chats send null — server ignores it
      'model': _model,
      'think': _thinkOn,
      'arena': useArena,
      if (rematch) 'rematch': true,
    };
    final endpoint = _agentMode && !rematch
        ? '/agents/stream'
        : useArena
            ? '/agents/arena/stream'
            : '/chat/stream';
    try {
      await for (final ev in Api.streamTo(endpoint, payload)) {
        switch (ev['type']) {
          case 'meta':
            _conversationId ??= ev['conversation_id'] as String?;
            break;
          case 'plan':
            setState(() {
              assistant.steps = [
                for (final st in (ev['steps'] as List? ?? []))
                  AgentStep(agent: st['agent'] as String? ?? 'agent', task: st['task'] as String? ?? ''),
              ];
            });
            break;
          case 'step_start':
            _markStep(ev, 'running');
            break;
          case 'step_done':
            _markStep(ev, 'done');
            break;
          case 'delta':
            setState(() => assistant.text += (ev['text'] as String?) ?? '');
            _scrollToBottom();
            break;
          case 'media_start': // 🎨🎬 in-chat creation started
            setState(() {
              assistant.media = ChatMedia(
                kind: '${ev['kind'] ?? 'image'}',
                prompt: ev['prompt'] as String?,
                pending: true,
              );
            });
            _scrollToBottom();
            break;
          case 'media_progress': // 🎬 reel pipeline stages
            setState(() {
              final md = assistant.media;
              if (md != null) {
                md
                  ..pending = true
                  ..stage = '${ev['stage'] ?? ''}'
                  ..done = (ev['done'] is num) ? (ev['done'] as num).toInt() : null
                  ..total = (ev['total'] is num) ? (ev['total'] as num).toInt() : null;
              }
            });
            break;
          case 'media': // ✅ artifact ready
            setState(() {
              assistant.media = ChatMedia(
                kind: '${ev['kind'] ?? 'image'}',
                url: ev['url'] as String?,
                prompt: ev['prompt'] as String?,
                stored: ev['stored'] as String?,
              );
            });
            _scrollToBottom();
            break;
          case 'topic':
            setState(() {
              assistant.arenaLive = ArenaLiveState(
                topic: ev['topic'] as String?,
                brand: ev['brand'] as String?,
                rematch: ev['rematch'] == true,
              );
            });
            break;
          case 'warning':
            setState(() => assistant.arenaLive?.warnings.add('${ev['message'] ?? ''}'));
            break;
          case 'draft_start':
            setState(() => assistant.arenaLive?.startDraft('${ev['provider'] ?? '?'}'));
            break;
          case 'draft_delta':
            // cap repaints: count chars without storing the whole text twice
            final t = '${ev['text'] ?? ''}';
            if (t.isNotEmpty) {
              setState(() => assistant.arenaLive?.addDelta('${ev['provider'] ?? '?'}', t.length));
            }
            break;
          case 'draft_done':
            setState(() => assistant.arenaLive?.finishDraft('${ev['provider'] ?? '?'}'));
            break;
          case 'vote_cast':
            setState(() {
              assistant.arenaLive?.votes.add(ArenaBallot(
                provider: '${ev['provider'] ?? '?'}',
                vote: ev['vote'] as String?,
                rationale: '${ev['rationale'] ?? ''}',
                invalid: ev['invalid'] == true || ev['vote'] == null,
              ));
            });
            break;
          case 'arena_verdict':
            setState(() {
              assistant.arenaData = ArenaVerdict.fromEvent(ev);
              assistant.arenaLive = null;
            });
            break;
          case 'thinking':
            setState(() {
              final ms = ev['think_time_ms'];
              if (ms is num) assistant.think = '🧠 reasoned ${(ms / 1000).toStringAsFixed(1)}s';
            });
            break;
          case 'error':
            setState(() => assistant.text = '⚠️ ${ev['message'] ?? 'Something went wrong'}');
            break;
        }
      }
      if (assistant.text.isEmpty && assistant.media == null) {
        setState(() => assistant.text = '⚠️ Empty response');
      }
    } catch (e) {
      setState(() => assistant.text = '⚠️ ${e.toString().replaceFirst('Exception: ', '')}');
    } finally {
      setState(() => _busy = false);
      _loadConversations();
    }
  }

  /// 🧠 Persisted thinking line for restored messages (matches the live stream label).
  static String? _thinkLine(dynamic meta) {
    if (meta is! Map || meta['mode'] != 'chat+think') return null;
    final ms = meta['think_time_ms'];
    if (ms is num && ms > 0) {
      return '🧠 reasoned ${ms >= 1000 ? '${(ms / 1000).toStringAsFixed(1)}s' : '${ms}ms'}';
    }
    return '🧠 extended reasoning';
  }

  /// ⚔️ Rematch: resend the last user question; drafters try to beat the prior winner.
  Future<void> _rematch() async {
    final lastUser = _messages.lastWhere((m) => m.role == 'user',
        orElse: () => ChatMsg(role: 'user', text: ''));
    if (lastUser.text.isEmpty || _busy) return;
    final wasArena = _arenaMode;
    _arenaMode = true; // force the arena pipeline for this send
    await _sendMessage(lastUser.text, rematch: true);
    _arenaMode = wasArena;
  }

  // display-name rule (web parity): users see S1 ChatMood-4 / S1 ChatMood-4-Fast labels,
  // never raw vendor ids (ids themselves stay = server routes on them)
  static const _pickerModels = [
    ['auto', '🚀', 'Auto · best pick per message'],
    ['grok-3-mini', '💸', 'Mini · cheapest, quick answers'],
    ['grok-4-fast', '⚡', 'S1 ChatMood-4-Fast · newest gen, 2M ctx'],
    ['grok-4', '👑', 'S1 ChatMood-4 · flagship (🧠 reasoning)'],
    ['grok-code-fast-1', '💻', 'Code · deep reasoning for code'],
  ];

  Future<void> _showModelPicker() async {
    await showModalBottomSheet(
      context: context,
      backgroundColor: lightPanel,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setSheet) => SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 10, 16, 20),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('Premium models', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: Colors.black87)),
                const SizedBox(height: 10),
                for (final m in _pickerModels)
                  ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    leading: Text(m[1], style: const TextStyle(fontSize: 18)),
                    title: Text(m[2], style: const TextStyle(color: Colors.black87, fontSize: 13, fontWeight: FontWeight.w500)),
                    trailing: _model == m[0] ? const Icon(Icons.check, color: lightAccent, size: 18) : null,
                    onTap: () {
                      setState(() => _model = m[0]);
                      setSheet(() {});
                    },
                  ),
                const Divider(color: lightLine, height: 18),
                SwitchListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  activeColor: lightAccent,
                  title: Text('🧠 Extended reasoning', style: TextStyle(color: (_model == 'auto' || _model == 'grok-4' || _model == 'grok-code-fast-1') ? Colors.black87 : Colors.black38, fontSize: 13, fontWeight: FontWeight.w500)),
                  subtitle: const Text('S1 ChatMood-4 (or code models) only', style: TextStyle(color: Colors.black38, fontSize: 11)),
                  value: _thinkOn && (_model == 'auto' || _model == 'grok-4' || _model == 'grok-code-fast-1'),
                  onChanged: (_model == 'auto' || _model == 'grok-4' || _model == 'grok-code-fast-1')
                      ? (v) {
                          setState(() => _thinkOn = v);
                          setSheet(() {});
                        }
                      : null,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  void _markStep(Map<String, dynamic> ev, String status) {
    final idx = ev['i'];
    if (idx is! int) return;
    setState(() {
      final steps = _messages.isEmpty ? null : _messages.last.steps;
      if (steps != null && idx < steps.length) {
        steps[idx].status = status;
        if (status == 'done') steps[idx].preview = ev['preview'] as String?;
      }
    });
  }

  // ------------------------------------------------------------------ files
  static const _audioExts = {'mp3', 'wav', 'm4a', 'ogg', 'opus', 'webm', 'flac'};

  Future<void> _attach() async {
    try {
      final result = await FilePicker.platform.pickFiles(withData: true);
      final f = result?.files.first;
      if (f == null || f.bytes == null) return;
      final ext = f.name.split('.').last.toLowerCase();
      if (_audioExts.contains(ext)) {
        await _analyzeAudio(f.bytes!, f.name);
        return;
      }
      final saved = await Api.postMultipart('/files', f.bytes!, f.name);
      setState(() => _files.add(AttachedFile(id: saved['id'] as String, filename: saved['filename'] as String)));
    } catch (e) {
      _toast('Upload failed: ${e.toString().replaceFirst('Exception: ', '')}');
    }
  }

  /// Audio pick → transcribe + AI analysis (lyrics / mood / "what song is this?"),
  /// landed as a normal exchange in the current conversation.
  Future<void> _analyzeAudio(List<int> bytes, String filename) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final res = await Api.analyzeAudio(bytes, filename, conversationId: _conversationId);
      _conversationId ??= res['conversation_id'] as String?;
      setState(() {
        _messages.add(ChatMsg(role: 'user', text: '🎵 $filename'));
        _messages.add(ChatMsg(role: 'assistant', text: res['analysis'] as String? ?? ''));
      });
      _scrollToBottom();
      _loadConversations();
    } catch (e) {
      _toast("Audio analysis failed: ${e.toString().replaceFirst('Exception: ', '')}");
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  // ------------------------------------------------------------------ voice
  Future<void> _toggleVoice() async {
    if (_busy) return;
    if (!_recording) {
      final granted = await _recorder.hasPermission();
      if (!granted) {
        _toast('Microphone permission denied');
        return;
      }
      final dir = await getTemporaryDirectory();
      _recordPath = '${dir.path}/mood_voice_${DateTime.now().millisecondsSinceEpoch}.m4a';
      await _recorder.start(const RecordConfig(encoder: AudioEncoder.aacLc), path: _recordPath!);
      setState(() => _recording = true);
      return;
    }
    final path = await _recorder.stop();
    setState(() {
      _recording = false;
      _busy = true;
    });
    try {
      final bytes = await File(path ?? _recordPath!).readAsBytes();
      final res = await Api.postMultipart(
        '/voice/chat',
        bytes,
        'voice.m4a',
        fields: {if (_conversationId != null) 'conversation_id': _conversationId!},
      );
      _conversationId ??= res['conversation_id'] as String?;
      setState(() {
        _messages.add(ChatMsg(role: 'user', text: '🎙️ ${res['transcript']}'));
        _messages.add(ChatMsg(role: 'assistant', text: res['reply'] as String? ?? ''));
      });
      _scrollToBottom();
      final audioB64 = res['audio_b64'] as String?;
      if (audioB64 != null && audioB64.isNotEmpty) {
        await _player.stop();
        await _player.play(BytesSource(base64Decode(audioB64)));
      }
      _loadConversations();
    } catch (e) {
      _toast('Voice failed: ${e.toString().replaceFirst('Exception: ', '')}');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _toast(String msg) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(_scroll.position.maxScrollExtent + 200,
            duration: const Duration(milliseconds: 200), curve: Curves.easeOut);
      }
    });
  }
        Future<void> _deleteAccountDialog() async {
          final pw = TextEditingController();
          var busy = false;
          String? err;
          final ok = await showDialog<bool>(
            context: context,
            barrierDismissible: false,
            builder: (ctx) => StatefulBuilder(builder: (ctx, setSt) => AlertDialog(
              backgroundColor: lightPanel,
              title: const Text('🗑 Delete account permanently?'),
              content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text(
                  'This erases EVERYTHING — chats, uploads, designs, films, memory, plugin tokens, and teams you own. It cannot be undone.',
                  style: TextStyle(fontSize: 12, color: Colors.grey),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: pw,
                  obscureText: true,
                  decoration: const InputDecoration(hintText: 'Type your password to confirm'),
                ),
                if (err != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(err!, style: const TextStyle(fontSize: 11, color: Colors.redAccent)),
                  ),
              ]),
              actions: [
                TextButton(onPressed: busy ? null : () => Navigator.pop(ctx, false), child: const Text('Keep my account')),
                FilledButton(
                  style: FilledButton.styleFrom(backgroundColor: Colors.red.shade700),
                  onPressed: busy
                      ? null
                      : () async {
                          if (pw.text.isEmpty) {
                            setSt(() => err = 'Enter your password');
                            return;
                          }
                          setSt(() { busy = true; err = null; });
                          try {
                            await Api.deleteMyAccount(pw.text);
                            if (ctx.mounted) Navigator.pop(ctx, true);
                          } catch (e) {
                            setSt(() { busy = false; err = '$e'; });
                          }
                        },
                  child: busy
                      ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                      : const Text('Delete forever'),
                ),
              ],
            )),
          );
          pw.dispose();
          if (ok == true && mounted) {
            await Api.setToken(null);
            if (!mounted) return;
            Navigator.of(context).pushAndRemoveUntil(
              MaterialPageRoute(builder: (_) => const LoginScreen()), (_) => false);
          }
        }


  Future<void> _logout() async {
    await Api.setToken(null);
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
      (_) => false,
    );
  }

  // 🏠 Ask | Imagine | Films — compact ChatGPT-style destination tabs
  // shown only on the empty chat home. Conversations keep the regular title.
  Widget _modeTabs() {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        _homeTabLabel('Ask', _homeTab == 0, () => setState(() => _homeTab = 0)),
        const SizedBox(width: 22),
        _homeTabLabel('Imagine', false, () {
          Navigator.of(context).push(MaterialPageRoute(builder: (_) => const DesignScreen()));
        }),
        const SizedBox(width: 22),
        _homeTabLabel('Films', false, () {
          Navigator.of(context).push(MaterialPageRoute(builder: (_) => const FilmsScreen()));
        }),
      ],
    );
  }

  Widget _homeTabLabel(String label, bool active, VoidCallback onTap) {
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(label,
              style: TextStyle(
                  fontSize: 15,
                  fontWeight: active ? FontWeight.w700 : FontWeight.w500,
                  color: active ? Colors.white : Colors.grey.shade500)),
          const SizedBox(height: 3),
          Container(
            height: 2.5,
            width: 22,
            decoration: BoxDecoration(
                color: active ? Colors.white : Colors.transparent,
                borderRadius: BorderRadius.circular(2)),
          ),
        ],
      ),
    );
  }

  String _modelLabel() {
    switch (_model) {
      case 'grok-3-mini':
        return 'Mini';
      case 'grok-4-fast':
        return 'S1 ChatMood-4-Fast';
      case 'grok-4':
        return 'S1 ChatMood-4';
      case 'grok-code-fast-1':
        return 'Code';
      default:
        return 'S1 ChatMood-4 · auto';
    }
  }

  Widget _quickChip(IconData icon, String label, VoidCallback? onTap) {
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: ActionChip(
        avatar: Icon(icon, size: 16, color: Colors.grey.shade400),
        label: Text(label, style: const TextStyle(fontSize: 12.5)),
        onPressed: onTap,
        backgroundColor: Colors.white.withOpacity(0.06),
        side: BorderSide(color: Colors.white.withOpacity(0.08)),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      ),
    );
  }

  // ─────────────────────────────────────────── 🏠 ChatGPT-style centered home (web parity)
  Widget _homeActionPill(IconData icon, String label, VoidCallback onTap) {
    return SizedBox(
      width: double.infinity,
      child: Material(
        color: const Color(0xFF262626),
        borderRadius: BorderRadius.circular(14),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(14),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 13),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: Colors.white.withOpacity(0.08)),
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(icon, color: const Color(0xFF35D6D0), size: 17),
                const SizedBox(width: 10),
                Flexible(
                  child: Text(
                    label,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      fontSize: 14,
                      color: Colors.grey.shade300,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  /// Empty chat home. The old mobile code still showed a formal light page and
  /// kept the composer pinned to the bottom, so it could never match the web
  /// ChatGPT home. Here the greeting, composer, model/search row and starters
  /// live in one centered column; the persistent bottom composer only returns
  /// after a conversation starts.
  Widget _centeredHome() {
    return LayoutBuilder(
      builder: (context, constraints) {
        final bottomInset = MediaQuery.of(context).viewInsets.bottom;
        return SingleChildScrollView(
          padding: EdgeInsets.fromLTRB(14, bottomInset > 0 ? 8 : 20, 14, 14),
          child: ConstrainedBox(
            constraints: BoxConstraints(minHeight: constraints.maxHeight > 28 ? constraints.maxHeight - 28 : 0),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                Container(
                  width: 58,
                  height: 58,
                  decoration: BoxDecoration(
                    color: Colors.black,
                    borderRadius: BorderRadius.circular(18),
                    border: Border.all(color: Colors.white.withOpacity(0.09)),
                    boxShadow: [
                      BoxShadow(
                        color: const Color(0xFF35D6D0).withOpacity(0.18),
                        blurRadius: 42,
                        spreadRadius: 2,
                      ),
                    ],
                  ),
                  padding: const EdgeInsets.all(7),
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(12),
                    child: Image.asset('assets/icon/app_icon.png', fit: BoxFit.cover),
                  ),
                ),
                const SizedBox(height: 12),
                Text(
                  'ChatMood',
                  style: TextStyle(
                    color: Colors.grey.shade200,
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                    letterSpacing: -0.2,
                  ),
                ),
                const SizedBox(height: 26),
                const Text(
                  'What can I help with?',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 32,
                    height: 1.08,
                    fontWeight: FontWeight.w800,
                    letterSpacing: -1.1,
                  ),
                ),
                const SizedBox(height: 28),
                ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 680),
                  child: Column(
                    children: [
                      if (_files.isNotEmpty) ...[
                        _filesRow(dark: true),
                        const SizedBox(height: 6),
                      ],
                      _composerRow(home: true),
                      const SizedBox(height: 10),
                      Wrap(
                        alignment: WrapAlignment.center,
                        spacing: 8,
                        runSpacing: 8,
                        children: [
                          _modeToggleChip(
                            icon: Icons.language,
                            label: _search ? 'Search on' : 'Search off',
                            active: _search,
                            onTap: () => setState(() => _search = !_search),
                          ),
                          _modeToggleChip(
                            icon: Icons.smart_toy_outlined,
                            label: _agentMode ? 'Agent on' : 'Agent',
                            active: _agentMode,
                            onTap: () => setState(() {
                              _agentMode = !_agentMode;
                              if (_agentMode) _arenaMode = false;
                            }),
                          ),
                          _modeToggleChip(
                            icon: Icons.shield_outlined,
                            label: _arenaMode ? 'Arena on' : 'Arena',
                            active: _arenaMode,
                            onTap: () => setState(() {
                              _arenaMode = !_arenaMode;
                              if (_arenaMode) _agentMode = false;
                            }),
                          ),
                          _modeToggleChip(
                            icon: Icons.tune,
                            label: _modelLabel(),
                            active: _thinkOn,
                            onTap: _showModelPicker,
                          ),
                        ],
                      ),
                      const SizedBox(height: 24),
                      _homeActionPill(
                        Icons.auto_awesome,
                        'Write or brainstorm',
                        () => _prefill('Help me write '),
                      ),
                      const SizedBox(height: 8),
                      _homeActionPill(
                        Icons.travel_explore,
                        'Research a topic',
                        () {
                          setState(() => _search = true);
                          _prefill('Research ');
                        },
                      ),
                      const SizedBox(height: 8),
                      _homeActionPill(
                        Icons.image_outlined,
                        'Create an image',
                        () => _prefill('Create an image of '),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _modeToggleChip({required IconData icon, required String label, required bool active, required VoidCallback onTap}) {
    return Material(
      color: active ? const Color(0xFF173E3D) : const Color(0xFF242424),
      borderRadius: BorderRadius.circular(22),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(22),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(22),
            border: Border.all(color: active ? const Color(0xFF35D6D0).withOpacity(0.38) : Colors.white.withOpacity(0.07)),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 15, color: active ? const Color(0xFF35D6D0) : Colors.grey.shade500),
              const SizedBox(width: 6),
              Text(
                label,
                style: TextStyle(
                  color: active ? Colors.white : Colors.grey.shade400,
                  fontSize: 11.5,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _filesRow({bool dark = false}) {
    return SizedBox(
      height: 34,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 12),
        itemCount: _files.length,
        separatorBuilder: (_, __) => const SizedBox(width: 6),
        itemBuilder: (context, i) => Chip(
          label: Text(
            _files[i].filename,
            style: TextStyle(fontSize: 11, color: dark ? Colors.grey.shade200 : Colors.black87),
          ),
          onDeleted: () => setState(() => _files.removeAt(i)),
          visualDensity: VisualDensity.compact,
          backgroundColor: dark ? const Color(0xFF262626) : null,
          deleteIconColor: dark ? Colors.grey.shade400 : null,
          side: dark ? BorderSide(color: Colors.white.withOpacity(0.08)) : null,
        ),
      ),
    );
  }

  Widget _composerRow({bool home = false}) {
    return ValueListenableBuilder<TextEditingValue>(
      valueListenable: _input,
      builder: (context, val, _) {
        final hasText = val.text.trim().isNotEmpty;
        final inputBg = home ? const Color(0xFF2A2A2A) : Colors.white;
        final inputBorder = home ? Colors.white.withOpacity(0.08) : const Color(0xFFE5E7EB);
        final inputShadow = home ? Colors.black.withOpacity(0.20) : Colors.black.withOpacity(0.04);
        final textColor = home ? Colors.white : Colors.black87;
        final hintColor = home ? Colors.grey.shade500 : Colors.black38;
        final iconColor = home ? Colors.grey.shade300 : Colors.black54;
        final accent = home ? const Color(0xFF26706D) : const Color(0xFF3F82F6);
        return Padding(
          padding: EdgeInsets.symmetric(horizontal: home ? 0 : 10, vertical: 8),
          child: Row(
            children: [
              Expanded(
                child: Container(
                  decoration: BoxDecoration(
                    color: inputBg,
                    borderRadius: BorderRadius.circular(home ? 26 : 28),
                    border: Border.all(color: inputBorder),
                    boxShadow: [
                      BoxShadow(
                        color: inputShadow,
                        blurRadius: 6,
                        offset: const Offset(0, 2),
                      ),
                    ],
                  ),
                  padding: const EdgeInsets.symmetric(horizontal: 4),
                  child: Row(
                    children: [
                      IconButton(
                        icon: Icon(Icons.add, color: iconColor, size: 22),
                        tooltip: 'Attach file',
                        onPressed: _busy ? null : _attach,
                      ),
                      Expanded(
                        child: TextField(
                          controller: _input,
                          minLines: 1,
                          maxLines: 5,
                          textInputAction: TextInputAction.send,
                          onSubmitted: (_) => _send(),
                          style: TextStyle(color: textColor, fontSize: 15),
                          decoration: InputDecoration(
                            hintText: _agentMode ? 'Give the agent team a goal…' : 'Ask ChatMood',
                            hintStyle: TextStyle(color: hintColor, fontSize: 15),
                            border: InputBorder.none,
                            enabledBorder: InputBorder.none,
                            focusedBorder: InputBorder.none,
                            contentPadding: const EdgeInsets.symmetric(vertical: 10, horizontal: 4),
                          ),
                        ),
                      ),
                      // Inside on the right of the chat box: show Send button if typing, otherwise Mic
                      _busy
                          ? Padding(
                              padding: const EdgeInsets.symmetric(horizontal: 8),
                              child: SizedBox(
                                width: 20,
                                height: 20,
                                child: CircularProgressIndicator(strokeWidth: 2, color: accent),
                              ),
                            )
                          : hasText
                              ? Container(
                                  margin: const EdgeInsets.only(right: 4),
                                  decoration: BoxDecoration(
                                    color: accent,
                                    shape: BoxShape.circle,
                                  ),
                                  child: IconButton(
                                    icon: const Icon(Icons.arrow_upward, color: Colors.white, size: 16),
                                    padding: EdgeInsets.zero,
                                    constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
                                    onPressed: _send,
                                  ),
                                )
                              : IconButton(
                                  icon: Icon(_recording ? Icons.stop : Icons.mic_none,
                                      size: 22, color: _recording ? Colors.redAccent : iconColor),
                                  tooltip: _recording ? 'Stop & send' : 'Voice message',
                                  onPressed: _busy && !_recording ? null : _toggleVoice,
                                ),
                    ],
                  ),
                ),
              ),
              if (!home) ...[
                const SizedBox(width: 8),
                // Always-visible Blue circular Voice Orb Wave button next to the chat box!
                GestureDetector(
                  onTap: _busy ? null : _toggleVoice,
                  child: Container(
                    width: 44,
                    height: 44,
                    decoration: const BoxDecoration(
                      color: Color(0xFF3F82F6),
                      shape: BoxShape.circle,
                    ),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Container(width: 2, height: 12, decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(1))),
                        const SizedBox(width: 2),
                        Container(width: 2, height: 18, decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(1))),
                        const SizedBox(width: 2),
                        Container(width: 2, height: 14, decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(1))),
                        const SizedBox(width: 2),
                        Container(width: 2, height: 10, decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(1))),
                      ],
                    ),
                  ),
                ),
              ],
            ],
          ),
        );
      },
    );
  }

  Widget _bottomTabBar({required bool emptyHome}) {
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(8, 6, 8, 8),
        child: Container(
          padding: const EdgeInsets.all(5),
          decoration: BoxDecoration(
            color: emptyHome ? const Color(0xFF2A2926) : Colors.white,
            borderRadius: BorderRadius.circular(24),
            border: Border.all(color: emptyHome ? Colors.white.withOpacity(0.08) : const Color(0xFFE5E7EB)),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withOpacity(emptyHome ? 0.22 : 0.05),
                blurRadius: 18,
                offset: const Offset(0, 8),
              ),
            ],
          ),
          child: Row(
            children: [
              _bottomTab(
                icon: Icons.chat_bubble_outline,
                label: 'Chat',
                active: true,
                dark: emptyHome,
                onTap: emptyHome ? () {} : _newChat,
              ),
              _bottomTab(
                icon: Icons.graphic_eq,
                label: 'Voice',
                active: _recording,
                dark: emptyHome,
                onTap: _busy && !_recording ? () {} : () => _toggleVoice(),
              ),
              _bottomTab(
                icon: Icons.image_outlined,
                label: 'Images',
                active: false,
                dark: emptyHome,
                onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const DesignScreen())),
              ),
              _bottomTab(
                icon: Icons.brush_outlined,
                label: 'Design',
                active: false,
                dark: emptyHome,
                onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const DesignScreen())),
              ),
              _bottomTab(
                icon: Icons.movie_creation_outlined,
                label: 'Films',
                active: false,
                dark: emptyHome,
                onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const FilmsScreen())),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _bottomTab({
    required IconData icon,
    required String label,
    required bool active,
    required bool dark,
    required VoidCallback onTap,
  }) {
    final bg = active ? (dark ? Colors.white : Colors.black87) : Colors.transparent;
    final fg = active ? (dark ? Colors.black87 : Colors.white) : (dark ? Colors.grey.shade500 : Colors.black45);
    return Expanded(
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 160),
          curve: Curves.easeOut,
          padding: const EdgeInsets.symmetric(vertical: 7),
          decoration: BoxDecoration(
            color: bg,
            borderRadius: BorderRadius.circular(18),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 19, color: fg),
              const SizedBox(height: 2),
              Text(
                label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(color: fg, fontSize: 10, fontWeight: active ? FontWeight.w700 : FontWeight.w500),
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final lightTheme = ThemeData(
      useMaterial3: true,
      brightness: Brightness.light,
      scaffoldBackgroundColor: lightBase,
      appBarTheme: const AppBarTheme(
        backgroundColor: Colors.transparent,
        elevation: 0,
        scrolledUnderElevation: 0,
      ),
      colorScheme: const ColorScheme.light(
        primary: lightAccent,
        surface: lightPanel,
        onSurface: Colors.black87,
        outline: lightLine,
      ),
    );
    final emptyHome = _messages.isEmpty;

    // any touch counts as activity for the 5-minute idle auto-home timer
    return Listener(
      onPointerDown: (_) => _poke(),
      behavior: HitTestBehavior.translucent,
      child: Theme(
        data: lightTheme,
        child: Scaffold(
          backgroundColor: emptyHome ? const Color(0xFF1F201E) : lightBase,
          appBar: AppBar(
            backgroundColor: emptyHome ? const Color(0xFF242421) : Colors.transparent,
            elevation: 0,
            scrolledUnderElevation: 0,
            automaticallyImplyLeading: false,
            leadingWidth: 70,
            leading: Padding(
              padding: const EdgeInsets.only(left: 16, top: 8, bottom: 8),
              child: Builder(
                builder: (ctx) => GestureDetector(
                  onTap: () => Scaffold.of(ctx).openDrawer(),
                  child: Container(
                    decoration: BoxDecoration(
                      color: emptyHome ? Colors.transparent : Colors.white,
                      shape: BoxShape.circle,
                      border: Border.all(color: emptyHome ? Colors.transparent : const Color(0xFFE5E7EB)),
                      boxShadow: emptyHome
                          ? []
                          : [
                              BoxShadow(
                                color: Colors.black.withOpacity(0.03),
                                blurRadius: 4,
                                offset: const Offset(0, 1),
                              ),
                            ],
                    ),
                    child: Center(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        crossAxisAlignment: CrossAxisAlignment.start,
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Container(width: 14, height: 2, color: emptyHome ? Colors.white : Colors.black87),
                          const SizedBox(height: 3),
                          Container(width: 9, height: 2, color: emptyHome ? Colors.white : Colors.black87),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ),
            centerTitle: true,
            title: emptyHome ? _modeTabs() : GestureDetector(
              onTap: () {
                _toast('Premium features & reasoning models unlocked! 🚀');
              },
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 7),
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(20),
                  border: Border.all(color: const Color(0xFFE5E7EB)),
                  boxShadow: [
                    BoxShadow(
                      color: Colors.black.withOpacity(0.02),
                      blurRadius: 3,
                      offset: const Offset(0, 1),
                    ),
                  ],
                ),
                child: const Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(Icons.auto_awesome, color: Colors.indigoAccent, size: 14),
                    SizedBox(width: 6),
                    Text(
                      'ChatMood',
                      style: TextStyle(
                        color: Colors.indigo,
                        fontWeight: FontWeight.w700,
                        fontSize: 12.5,
                      ),
                    ),
                  ],
                ),
              ),
            ),
            actions: [
              Padding(
                padding: const EdgeInsets.only(right: 16, top: 8, bottom: 8),
                child: GestureDetector(
                  onTap: () {
                    Navigator.of(context).push(MaterialPageRoute(builder: (_) => const FilmsScreen()));
                  },
                  child: Container(
                    width: 40,
                    height: 40,
                    decoration: BoxDecoration(
                      color: emptyHome ? Colors.transparent : Colors.white,
                      shape: BoxShape.circle,
                      border: Border.all(color: emptyHome ? Colors.transparent : const Color(0xFFE5E7EB)),
                      boxShadow: emptyHome
                          ? []
                          : [
                              BoxShadow(
                                color: Colors.black.withOpacity(0.03),
                                blurRadius: 4,
                                offset: const Offset(0, 1),
                              ),
                            ],
                    ),
                    child: Icon(Icons.movie_creation_outlined, color: emptyHome ? Colors.white : Colors.black87, size: 18),
                  ),
                ),
              ),
            ],
          ),
          drawer: Drawer(
            backgroundColor: lightPanel,
            child: SafeArea(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Padding(
                    padding: const EdgeInsets.all(16),
                    child: FilledButton.icon(
                      onPressed: _newChat,
                      icon: const Icon(Icons.add, size: 18),
                      label: const Text('New chat'),
                      style: FilledButton.styleFrom(
                        backgroundColor: lightAccent,
                        foregroundColor: Colors.white,
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                      ),
                    ),
                  ),
                  const Padding(
                    padding: EdgeInsets.fromLTRB(16, 10, 16, 0),
                    child: Text('AI MODES', style: TextStyle(fontSize: 10, letterSpacing: 1.2, color: Colors.grey)),
                  ),
                  SwitchListTile.adaptive(
                    dense: true,
                    secondary: const Icon(Icons.shield_outlined, size: 18),
                    title: const Text('⚔️ Arena Mode', style: TextStyle(fontSize: 13)),
                    subtitle: const Text('models debate, S1 ChatMood-4 judges',
                        style: TextStyle(fontSize: 10, color: Colors.grey)),
                    value: _arenaMode,
                    onChanged: (v) => setState(() {
                      _arenaMode = v;
                      if (v) _agentMode = false;
                    }),
                  ),
                  SwitchListTile.adaptive(
                    dense: true,
                    secondary: const Icon(Icons.smart_toy_outlined, size: 18),
                    title: const Text('Agent team', style: TextStyle(fontSize: 13)),
                    subtitle: const Text('planner → specialists → writer',
                        style: TextStyle(fontSize: 10, color: Colors.grey)),
                    value: _agentMode,
                    onChanged: (v) => setState(() {
                      _agentMode = v;
                      if (v) _arenaMode = false;
                    }),
                  ),
                  SwitchListTile.adaptive(
                    dense: true,
                    secondary: const Icon(Icons.public, size: 18),
                    title: const Text('Live search', style: TextStyle(fontSize: 13)),
                    subtitle: const Text('cite fresh web sources in answers',
                        style: TextStyle(fontSize: 10, color: Colors.grey)),
                    value: _search,
                    onChanged: (v) => setState(() => _search = v),
                  ),
                  ListTile(
                    dense: true,
                    leading: const Icon(Icons.tune, size: 18),
                    title: const Text('Model & reasoning', style: TextStyle(fontSize: 13)),
                    subtitle: Text(_modelLabel(), style: const TextStyle(fontSize: 10, color: Colors.grey)),
                    onTap: () {
                      Navigator.of(context).maybePop();
                      _showModelPicker();
                    },
                  ),
                  Theme(
                    data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
                    child: ExpansionTile(
                      dense: true,
                      tilePadding: const EdgeInsets.symmetric(horizontal: 16),
                      childrenPadding: EdgeInsets.zero,
                      leading: Icon(
                        _workspace == null ? Icons.person_outline : Icons.group_outlined,
                        size: 18,
                      ),
                      title: Text(
                        _workspace?.name ?? 'Personal',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
                      ),
                      subtitle: Text(
                        _workspace == null ? 'Personal chats · switch to a team' : 'Team workspace · shared',
                        style: const TextStyle(fontSize: 10, color: Colors.grey),
                      ),
                      children: [
                        ListTile(
                          dense: true,
                          selected: _workspace == null,
                          leading: const Icon(Icons.person_outline, size: 16),
                          title: const Text('Personal', style: TextStyle(fontSize: 13)),
                          onTap: () => _selectWorkspace(null),
                        ),
                        for (final w in _workspaces)
                          ListTile(
                            dense: true,
                            selected: _workspace?.id == w.id,
                            leading: const Icon(Icons.group_outlined, size: 16),
                            title: Text(w.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 13)),
                            onTap: () => _selectWorkspace(w),
                          ),
                        ListTile(
                          dense: true,
                          leading: const Icon(Icons.link, size: 16),
                          title: const Text('Join with invite…', style: TextStyle(fontSize: 13)),
                          onTap: () {
                            Navigator.of(context).maybePop();
                            _joinInvite();
                          },
                        ),
                      ],
                    ),
                  ),
                  Expanded(
                    child: ListView.builder(
                      itemCount: _conversations.length,
                      itemBuilder: (context, i) {
                        final c = _conversations[i];
                        return ListTile(
                          dense: true,
                          selected: c.id == _conversationId,
                          title: Text(c.title, maxLines: 1, overflow: TextOverflow.ellipsis),
                          onTap: () => _openConversation(c.id),
                        );
                      },
                    ),
                  ),
                  const Divider(height: 1, color: lightLine),
                  ListTile(
                    leading: const Icon(Icons.alarm, size: 18),
                    title: const Text('⏰ Tasks', style: TextStyle(fontSize: 14)),
                    subtitle: const Text('Prompts ChatMood runs on a schedule',
                        style: TextStyle(fontSize: 10, color: Colors.grey)),
                    onTap: () {
                      Navigator.of(context).maybePop();
                      Navigator.of(context).push(MaterialPageRoute(builder: (_) => const TasksScreen()));
                    },
                  ),
                  ListTile(
                    leading: const Icon(Icons.movie_creation_outlined, size: 18),
                    title: const Text('🎞 Films'),
                    subtitle: const Text('Your storyboard movies', style: TextStyle(fontSize: 10, color: Colors.grey)),
                    onTap: () {
                      Navigator.of(context).maybePop();
                      Navigator.of(context).push(MaterialPageRoute(builder: (_) => const FilmsScreen()));
                    },
                  ),
                  ListTile(
                    leading: const Icon(Icons.palette_outlined, size: 18),
                    title: const Text('Design Studio', style: TextStyle(fontSize: 14)),
                    onTap: () {
                      Navigator.of(context).pop();
                      Navigator.of(context).push(MaterialPageRoute(builder: (_) => const DesignScreen()));
                    },
                  ),
                  ListTile(
                    leading: const Icon(Icons.content_cut, size: 18),
                    title: const Text('✂️ Auto-Edit', style: TextStyle(fontSize: 14)),
                    subtitle: const Text('Upload a clip · edit by instruction', style: TextStyle(fontSize: 10, color: Colors.grey)),
                    onTap: () {
                      Navigator.of(context).pop();
                      Navigator.of(context).push(MaterialPageRoute(builder: (_) => const EditScreen()));
                    },
                  ),
                  ListTile(
                    leading: const Icon(Icons.request_page_outlined, size: 18),
                    title: const Text('🛍 Client Orders', style: TextStyle(fontSize: 14)),
                    subtitle: const Text('Magic links clients order from', style: TextStyle(fontSize: 10, color: Colors.grey)),
                    onTap: () {
                      Navigator.of(context).pop();
                      Navigator.of(context).push(MaterialPageRoute(builder: (_) => const OrdersScreen()));
                    },
                  ),
                  ListTile(
                    leading: const Icon(Icons.logout, size: 18),
                    title: const Text('Sign out'),
                    onTap: _logout,
                  ),
                  ListTile(
                    leading: Icon(Icons.delete_forever_outlined, size: 18, color: Colors.red.shade400),
                    title: Text('Delete account', style: TextStyle(fontSize: 14, color: Colors.red.shade300)),
                    subtitle: const Text('Erase everything — required by the app stores',
                        style: TextStyle(fontSize: 10, color: Colors.grey)),
                    onTap: () {
                      Navigator.of(context).maybePop();
                      _deleteAccountDialog();
                    },
                  ),
                ],
              ),
            ),
          ),
          body: Column(
            children: [
              if (!emptyHome && _agentMode)
                Container(
                  width: double.infinity,
                  color: lightPanel,
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: const Text(
                    '🤖 Agent team — planner, concurrent specialists, writer & critic',
                    textAlign: TextAlign.center,
                    style: TextStyle(fontSize: 11, color: Colors.grey),
                  ),
                ),
              if (!emptyHome && _workspace != null)
                Container(
                  width: double.infinity,
                  color: lightPanel,
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Text(
                    '👥 Team · ${_workspace!.name} — conversations shared with all members',
                    textAlign: TextAlign.center,
                    style: const TextStyle(fontSize: 11, color: Colors.grey),
                  ),
                ),
              Expanded(
                child: emptyHome
                    ? _centeredHome()
                    : ListView.builder(
                        controller: _scroll,
                        padding: const EdgeInsets.all(12),
                        itemCount: _messages.length,
                        itemBuilder: (context, i) => _Bubble(
                              _messages[i],
                              canRematch: !_busy,
                              onRematch: _rematch,
                            ),
                      ),
              ),
              if (!emptyHome && _files.isNotEmpty) _filesRow(),
              if (!emptyHome)
                SafeArea(
                  top: false,
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(8, 4, 8, 4),
                    child: _composerRow(),
                  ),
                ),
              _bottomTabBar(emptyHome: emptyHome),
            ],
          ),
        ),
      ),
    );
  }
}

class _Bubble extends StatelessWidget {
  const _Bubble(this.msg, {this.canRematch = false, this.onRematch});
  final ChatMsg msg;
  final bool canRematch; // arena verdict visible + screen not busy
  final VoidCallback? onRematch;

  @override
  Widget build(BuildContext context) {
    if (msg.role == 'user') {
      return Align(
        alignment: Alignment.centerRight,
        child: Container(
          margin: const EdgeInsets.only(bottom: 12, left: 48),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          decoration: BoxDecoration(
            color: lightAccent.withOpacity(0.12),
            border: Border.all(color: lightAccent.withOpacity(0.25)),
            borderRadius: BorderRadius.circular(16),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            mainAxisSize: MainAxisSize.min,
            children: [
              if (msg.author != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: 3),
                  child: Text(
                    msg.author!,
                    style: const TextStyle(fontSize: 10, color: Colors.black54, fontWeight: FontWeight.w600),
                  ),
                ),
              Text(
                msg.text,
                style: const TextStyle(color: Colors.black87, fontSize: 15, height: 1.4),
              ),
            ],
          ),
        ),
      );
    }
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (msg.steps != null && msg.steps!.isNotEmpty)
            Container(
              margin: const EdgeInsets.only(bottom: 8),
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: lightPanel,
                border: Border.all(color: lightLine),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('🤖 Agent team', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: Colors.black87)),
                  const SizedBox(height: 6),
                  for (final s in msg.steps!)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 2),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(s.status == 'done' ? '✅' : s.status == 'running' ? '⏳' : '▫️'),
                          const SizedBox(width: 6),
                          Expanded(
                            child: Text(
                              '${_icon(s.agent)} ${s.agent} — ${s.task}',
                              style: const TextStyle(fontSize: 11, color: Colors.black54),
                            ),
                          ),
                        ],
                      ),
                    ),
                ],
              ),
            ),
          if (msg.think != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Text(msg.think!, style: const TextStyle(fontSize: 11, color: lightAccent, fontWeight: FontWeight.w600)),
            ),
          if (msg.arenaLive != null || msg.arenaData != null)
            ArenaPanel(
              live: msg.arenaLive,
              verdict: msg.arenaData,
              onRematch: msg.arenaData != null && canRematch ? onRematch : null,
            ),
          if (msg.media != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: _MediaCard(media: msg.media!),
            ),
          msg.text.isEmpty
              ? (msg.media == null
                  ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                  : const SizedBox.shrink())
              : SelectionArea(
                  child: MarkdownBody(
                    data: msg.text,
                    styleSheet: MarkdownStyleSheet.fromTheme(Theme.of(context))
                        .copyWith(p: const TextStyle(fontSize: 15, height: 1.45, color: Colors.black87)),
                  ),
                ),
        ],
      ),
    );
  }

  String _icon(String agent) => switch (agent) {
        'researcher' => '🔍',
        'coder' => '⌨️',
        'writer' => '✍️',
        'critic' => '🧐',
        _ => '🤖',
      };
}

/// 🎨🎬 In-chat creation card: shimmer-ish progress while generating →
/// image (tap = fullscreen) or an inline video player (lazy init on first play).
class _MediaCard extends StatelessWidget {
  const _MediaCard({required this.media});
  final ChatMedia media;

  String get _stageLabel {
    if (media.kind == 'image') return '🎨 Painting your image…';
    if (media.stage == 'storyboard') return '🎞️ Storyboarding your reel…';
    if (media.stage == 'voice') return '🔊 Recording the voiceover…';
    if (media.stage == 'compositing') return '🎞️ Compositing your reel…';
    if (media.stage == 'scenes' && media.total != null) {
      return '🎬 Directing scenes (${media.done ?? 0}/${media.total})…';
    }
    return '🎬 Directing your reel…';
  }

  @override
  Widget build(BuildContext context) {
    final radius = BorderRadius.circular(16);
    if (media.pending || media.url == null) {
      return ClipRRect(
        borderRadius: radius,
        child: Container(
          decoration: BoxDecoration(
            color: MoodColors.panel,
            border: Border.all(color: MoodColors.line),
            borderRadius: radius,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const AspectRatio(aspectRatio: 16 / 9, child: Center(child: CircularProgressIndicator(strokeWidth: 2))),
              Padding(
                padding: const EdgeInsets.all(10),
                child: Text(_stageLabel, style: const TextStyle(fontSize: 11, color: Colors.grey)),
              ),
            ],
          ),
        ),
      );
    }
    return ClipRRect(
      borderRadius: radius,
      child: Container(
        decoration: BoxDecoration(
          color: Colors.black,
          border: Border.all(color: MoodColors.line),
          borderRadius: radius,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (media.kind == 'image')
              GestureDetector(
                onTap: () => showDialog(
                  context: context,
                  builder: (_) => Dialog(
                    backgroundColor: Colors.black,
                    insetPadding: EdgeInsets.zero,
                    child: Stack(
                      children: [
                        Center(child: InteractiveViewer(child: Image.network(media.url!))),
                        const Positioned(top: 40, right: 16, child: CloseButton(color: Colors.white)),
                      ],
                    ),
                  ),
                ),
                child: Image.network(
                  media.url!,
                  fit: BoxFit.cover,
                  loadingBuilder: (c, w, p) => p == null
                      ? w
                      : const AspectRatio(aspectRatio: 1, child: Center(child: CircularProgressIndicator(strokeWidth: 2))),
                  errorBuilder: (_, __, ___) => const Padding(
                    padding: EdgeInsets.all(24),
                    child: Text('🖼️ image unavailable — link may have expired', style: TextStyle(fontSize: 12, color: Colors.grey)),
                  ),
                ),
              )
            else
              _InlineVideo(url: media.url!),
            if ((media.prompt ?? '').isNotEmpty)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(
                        '${media.kind == 'image' ? '🎨' : '🎬'} ${media.prompt}',
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontSize: 10, color: Colors.grey),
                      ),
                    ),
                    if (media.stored == 'r2') const Text('☁️', style: TextStyle(fontSize: 10)),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// Inline chat video: 16:9 placeholder with a play affordance; the controller
/// initializes lazily on first tap so restored histories stay light.
class _InlineVideo extends StatefulWidget {
  const _InlineVideo({required this.url});
  final String url;

  @override
  State<_InlineVideo> createState() => _InlineVideoState();
}

class _InlineVideoState extends State<_InlineVideo> {
  VideoPlayerController? _c;
  bool _loading = false;
  bool _failed = false;

  Future<void> _toggle() async {
    if (_loading) return;
    try {
      if (_c == null) {
        setState(() => _loading = true);
        final c = VideoPlayerController.networkUrl(Uri.parse(widget.url));
        _c = c;
        await c.initialize();
        await c.play();
      } else if (_c!.value.isPlaying) {
        await _c!.pause();
      } else {
        await _c!.play();
      }
    } catch (_) {
      _failed = true;
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  void dispose() {
    _c?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final ready = _c != null && _c!.value.isInitialized && !_failed;
    return AspectRatio(
      aspectRatio: ready ? _c!.value.aspectRatio : 16 / 9,
      child: Stack(
        alignment: Alignment.center,
        children: [
          if (ready) VideoPlayer(_c!),
          if (_failed)
            const Padding(
              padding: EdgeInsets.all(16),
              child: Text('🎬 video unavailable — link may have expired', style: TextStyle(fontSize: 12, color: Colors.grey)),
            ),
          GestureDetector(
            onTap: _toggle,
            behavior: HitTestBehavior.opaque,
            child: Center(
              child: _loading
                  ? const CircularProgressIndicator(strokeWidth: 2)
                  : Icon(
                      ready && _c!.value.isPlaying ? Icons.pause_circle_filled : Icons.play_circle_fill,
                      size: 52,
                      color: Colors.white.withOpacity(0.9),
                    ),
            ),
          ),
          if (ready)
            Positioned(
              left: 0,
              right: 0,
              bottom: 0,
              child: VideoProgressIndicator(_c!, allowScrubbing: true, padding: EdgeInsets.zero),
            ),
        ],
      ),
    );
  }
}

class ScrollingGreeting extends StatefulWidget {
  const ScrollingGreeting({super.key, required this.text});
  final String text;

  @override
  State<ScrollingGreeting> createState() => _ScrollingGreetingState();
}

class _ScrollingGreetingState extends State<ScrollingGreeting> {
  late ScrollController _scrollController;
  bool _scrolling = false;

  @override
  void initState() {
    super.initState();
    _scrollController = ScrollController();
    WidgetsBinding.instance.addPostFrameCallback((_) => _loopScroll());
  }

  Future<void> _loopScroll() async {
    if (!mounted) return;
    _scrolling = true;
    while (_scrolling && mounted) {
      if (_scrollController.hasClients) {
        final maxScroll = _scrollController.position.maxScrollExtent;
        if (maxScroll > 0) {
          await _scrollController.animateTo(
            maxScroll,
            duration: Duration(seconds: (maxScroll / 45).round() + 3),
            curve: Curves.linear,
          );
          if (mounted) {
            _scrollController.jumpTo(0);
          }
        }
      }
      await Future.delayed(const Duration(milliseconds: 100));
    }
  }

  @override
  void dispose() {
    _scrolling = false;
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 36,
      child: ListView(
        controller: _scrollController,
        scrollDirection: Axis.horizontal,
        physics: const NeverScrollableScrollPhysics(),
        children: [
          SizedBox(width: MediaQuery.of(context).size.width),
          Center(
            child: Text(
              widget.text,
              style: const TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w600,
                color: Colors.black87,
                letterSpacing: 0.1,
              ),
            ),
          ),
          SizedBox(width: MediaQuery.of(context).size.width),
        ],
      ),
    );
  }
}
