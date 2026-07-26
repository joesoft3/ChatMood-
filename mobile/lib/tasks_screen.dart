// ⏰ Tasks — saved prompts Mood runs unattended, on a schedule.
//
// Mobile parity for the web /tasks page. This is arguably the surface that
// matters MOST on a phone: a scheduled run finishes while the app is closed and
// arrives as a push notification, so the phone is where people actually consume
// task output. The screen therefore prioritises: see the schedule, pause it,
// run it now, read the last result.
//
// Times are stored in UTC by the API; we render the local equivalent so nobody
// has to do timezone arithmetic in their head.
import 'dart:async';

import 'package:flutter/material.dart';

import 'api.dart';
import 'main.dart' show MoodColors;

class TasksScreen extends StatefulWidget {
  const TasksScreen({super.key});

  @override
  State<TasksScreen> createState() => _TasksScreenState();
}

class _TasksScreenState extends State<TasksScreen> {
  List<Map<String, dynamic>> _tasks = [];
  int _limit = 0;
  String _plan = '';
  bool _schedulerOn = true;
  bool _loading = true;
  String? _error;
  String? _busyId;
  Timer? _poll;

  @override
  void initState() {
    super.initState();
    _refresh();
    // Only needed while something is mid-run; cheap enough to keep simple.
    _poll = Timer.periodic(const Duration(seconds: 8), (_) {
      if (_tasks.any((t) => t['last_status'] == 'running')) _refresh(quiet: true);
    });
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  Future<void> _refresh({bool quiet = false}) async {
    try {
      final res = await Api.get('/tasks');
      if (!mounted) return;
      setState(() {
        _tasks = ((res['tasks'] as List?) ?? []).cast<Map<String, dynamic>>();
        _limit = (res['limit'] as num?)?.toInt() ?? 0;
        _plan = (res['plan'] as String?) ?? '';
        _schedulerOn = res['scheduler'] != false;
        _loading = false;
        if (!quiet) _error = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        if (!quiet) _error = '$e';
      });
    }
  }

  Future<void> _toggle(Map<String, dynamic> t) async {
    setState(() => _busyId = t['id'] as String);
    try {
      await Api.patch('/tasks/${t['id']}', {'enabled': !(t['enabled'] == true)});
      await _refresh(quiet: true);
    } catch (e) {
      _snack('$e');
    } finally {
      if (mounted) setState(() => _busyId = null);
    }
  }

  Future<void> _runNow(Map<String, dynamic> t) async {
    setState(() => _busyId = t['id'] as String);
    _snack('Running “${t['title']}”…');
    try {
      await Api.post('/tasks/${t['id']}/run', const {});
      await _refresh(quiet: true);
      _snack('✅ ${t['title']} finished — open its thread in chat.');
    } catch (e) {
      _snack('$e');
    } finally {
      if (mounted) setState(() => _busyId = null);
    }
  }

  Future<void> _delete(Map<String, dynamic> t) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: MoodColors.panel,
        title: Text('Delete “${t['title']}”?', style: const TextStyle(fontSize: 15)),
        content: const Text(
          'The schedule stops. Past answers stay in the chat thread.',
          style: TextStyle(fontSize: 12, color: Colors.grey),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Delete', style: TextStyle(color: Colors.redAccent)),
          ),
        ],
      ),
    );
    if (ok != true) return;
    setState(() => _busyId = t['id'] as String);
    try {
      await Api.delete('/tasks/${t['id']}');
      await _refresh(quiet: true);
    } catch (e) {
      _snack('$e');
    } finally {
      if (mounted) setState(() => _busyId = null);
    }
  }

  void _snack(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(msg, style: const TextStyle(fontSize: 12))));
  }

  /// "in 3h" / "5m ago" — the API sends ISO-8601 UTC.
  String _when(String? iso) {
    if (iso == null || iso.isEmpty) return '—';
    DateTime? t = DateTime.tryParse(iso.endsWith('Z') || iso.contains('+') ? iso : '${iso}Z');
    if (t == null) return '—';
    final diff = t.difference(DateTime.now());
    final mins = diff.inMinutes.abs();
    final rel = mins < 60
        ? '${mins}m'
        : mins < 1440
            ? '${(mins / 60).round()}h'
            : '${(mins / 1440).round()}d';
    return diff.isNegative ? '$rel ago' : 'in $rel';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: MoodColors.base,
      appBar: AppBar(
        title: const Text('⏰ Tasks', style: TextStyle(fontSize: 16)),
        backgroundColor: MoodColors.panel,
        actions: [
          IconButton(icon: const Icon(Icons.refresh, size: 20), onPressed: () => _refresh()),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () => _refresh(),
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : ListView(
                padding: const EdgeInsets.all(12),
                children: [
                  if (_error != null)
                    _notice(_error!, Colors.orangeAccent)
                  else if (!_schedulerOn)
                    _notice(
                      'The background scheduler is off on this deployment — tasks won\'t fire '
                      'automatically, but "Run now" still works.',
                      Colors.orangeAccent,
                    ),
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    child: Text(
                      _tasks.isEmpty
                          ? 'Schedule prompts on the web app — results arrive here as notifications.'
                          : '${_tasks.length} task${_tasks.length == 1 ? '' : 's'}'
                              '${_limit > 0 ? ' · $_limit allowed on $_plan' : ''}',
                      style: const TextStyle(fontSize: 11, color: Colors.grey),
                    ),
                  ),
                  if (_tasks.isEmpty && _error == null)
                    const Padding(
                      padding: EdgeInsets.only(top: 60),
                      child: Column(
                        children: [
                          Text('⏰', style: TextStyle(fontSize: 40)),
                          SizedBox(height: 10),
                          Text('No scheduled tasks yet',
                              style: TextStyle(fontSize: 13, color: Colors.white70)),
                          SizedBox(height: 6),
                          Padding(
                            padding: EdgeInsets.symmetric(horizontal: 24),
                            child: Text(
                              'Tasks turn Mood from something you ask into something that shows up — '
                              'a morning briefing, a weekly scan, any prompt you\'d otherwise retype.',
                              textAlign: TextAlign.center,
                              style: TextStyle(fontSize: 11, color: Colors.grey),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ..._tasks.map(_card),
                ],
              ),
      ),
    );
  }

  Widget _notice(String text, Color color) => Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: color.withOpacity(0.10),
          border: Border.all(color: color.withOpacity(0.30)),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Text(text, style: TextStyle(fontSize: 11, color: color)),
      );

  Widget _card(Map<String, dynamic> t) {
    final enabled = t['enabled'] == true;
    final busy = _busyId == t['id'];
    final status = (t['last_status'] as String?) ?? '';
    return Opacity(
      opacity: enabled ? 1 : 0.55,
      child: Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: MoodColors.panel,
          border: Border.all(color: MoodColors.line),
          borderRadius: BorderRadius.circular(14),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    (t['title'] as String?) ?? 'Task',
                    style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                if (status == 'running')
                  const SizedBox(
                    width: 12, height: 12, child: CircularProgressIndicator(strokeWidth: 2))
                else if (status == 'ok')
                  const Icon(Icons.check_circle, size: 14, color: Colors.greenAccent)
                else if (status == 'failed')
                  const Icon(Icons.error_outline, size: 14, color: Colors.redAccent),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              (t['prompt'] as String?) ?? '',
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 11, color: Colors.grey),
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 10,
              runSpacing: 4,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Text((t['schedule_label'] as String?) ?? '',
                    style: const TextStyle(fontSize: 10, color: Colors.white60)),
                if (enabled && t['next_run_at'] != null)
                  Text('next ${_when(t['next_run_at'] as String?)}',
                      style: const TextStyle(fontSize: 10, color: Colors.white38)),
                Text('${t['mode']}', style: const TextStyle(fontSize: 10, color: Colors.white38)),
                if ((t['run_count'] as num?) != null && (t['run_count'] as num) > 0)
                  Text('${t['run_count']} runs',
                      style: const TextStyle(fontSize: 10, color: Colors.white38)),
              ],
            ),
            if (status == 'failed' && (t['last_error'] as String?)?.isNotEmpty == true)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(t['last_error'] as String,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 10, color: Colors.redAccent)),
              ),
            const SizedBox(height: 6),
            Row(
              children: [
                TextButton.icon(
                  onPressed: busy ? null : () => _runNow(t),
                  icon: const Icon(Icons.bolt, size: 15),
                  label: const Text('Run now', style: TextStyle(fontSize: 11)),
                ),
                TextButton.icon(
                  onPressed: busy ? null : () => _toggle(t),
                  icon: Icon(enabled ? Icons.pause : Icons.play_arrow, size: 15),
                  label: Text(enabled ? 'Pause' : 'Resume', style: const TextStyle(fontSize: 11)),
                ),
                const Spacer(),
                IconButton(
                  onPressed: busy ? null : () => _delete(t),
                  icon: const Icon(Icons.delete_outline, size: 17, color: Colors.white38),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
