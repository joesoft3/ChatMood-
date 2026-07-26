import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

/// Thin client for the Mood AI API (FastAPI, /api/v1).
/// Pass the API root at build/run time:
///   flutter run --dart-define=API_URL=http://192.168.1.10:8000/api/v1
/// Default targets the Android emulator's host loopback.
class Api {
  static const String baseUrl =
      String.fromEnvironment('API_URL', defaultValue: 'http://10.0.2.2:8000/api/v1');

  static final String _apiRoot = baseUrl.replaceFirst(RegExp(r'/+$'), '');
  static const _tokenKey = 'mood_token';
  static final http.Client _client = http.Client();

  // ------------------------------------------------------------------ auth
  static Future<String?> getToken() async =>
      (await SharedPreferences.getInstance()).getString(_tokenKey);

  static Future<void> setToken(String? token) async {
    final prefs = await SharedPreferences.getInstance();
    if (token == null) {
      await prefs.remove(_tokenKey);
    } else {
      await prefs.setString(_tokenKey, token);
    }
  }

  static Uri _uri(String pathOrUrl) {
    final parsed = Uri.tryParse(pathOrUrl);
    if (parsed != null && parsed.hasScheme) return parsed;
    final path = pathOrUrl.startsWith('/') ? pathOrUrl : '/$pathOrUrl';
    return Uri.parse('$_apiRoot$path');
  }

  static bool _shouldAttachAuth(String pathOrUrl) {
    final parsed = Uri.tryParse(pathOrUrl);
    if (parsed == null || !parsed.hasScheme) return true;
    final api = Uri.parse(_apiRoot);
    return parsed.host == api.host && parsed.port == api.port;
  }

  static Map<String, String> _headers(String? token, {bool json = true}) => {
        if (json) 'Content-Type': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
      };

  static Future<void> _maybeExpire(http.BaseResponse res) async {
    if (res.statusCode == 401) await setToken(null);
  }

  static String _error(http.Response res) {
    try {
      final body = jsonDecode(res.body);
      final detail = body is Map ? body['detail'] : null;
      if (detail is String) return detail;
      if (detail is List) {
        return detail.map((d) {
          if (d is! Map) return '$d';
          final locRaw = d['loc'];
          final loc = locRaw is List
              ? locRaw.where((x) => '$x' != 'body').join('.')
              : 'request';
          return d['msg'] == null ? jsonEncode(d) : '$loc: ${d['msg']}';
        }).join('; ');
      }
      final message = body is Map ? body['message'] : null;
      if (message is String) return message;
      return jsonEncode(body);
    } catch (_) {
      return 'HTTP ${res.statusCode}';
    }
  }

  static dynamic _decodeJson(String body) => body.isEmpty ? <String, dynamic>{} : jsonDecode(body);

  static Map<String, dynamic> _asMap(dynamic body) =>
      body is Map ? body.cast<String, dynamic>() : <String, dynamic>{};

  // -------------------------------------------------------------- REST calls
  static Future<Map<String, dynamic>> post(String path, Map<String, dynamic> body,
      {Duration timeout = const Duration(seconds: 30)}) async {
    final token = _shouldAttachAuth(path) ? await getToken() : null;
    final res = await _client
        .post(_uri(path), headers: _headers(token), body: jsonEncode(body))
        .timeout(timeout);
    await _maybeExpire(res);
    if (res.statusCode >= 400) throw Exception(_error(res));
    return _asMap(_decodeJson(res.body));
  }

  /// Binary download with auth header (Design Studio PNG tiers, etc.). Accepts
  /// both API-relative paths and absolute media URLs returned by the backend.
  static Future<Uint8List> getBytes(String pathOrUrl,
      {Duration timeout = const Duration(seconds: 60)}) async {
    final token = _shouldAttachAuth(pathOrUrl) ? await getToken() : null;
    final res = await _client
        .get(_uri(pathOrUrl), headers: _headers(token, json: false))
        .timeout(timeout);
    await _maybeExpire(res);
    if (res.statusCode >= 400) throw Exception(_error(res));
    return res.bodyBytes;
  }

  static Future<dynamic> get(String path) async {
    final token = _shouldAttachAuth(path) ? await getToken() : null;
    final res = await _client
        .get(_uri(path), headers: _headers(token, json: false))
        .timeout(const Duration(seconds: 30));
    await _maybeExpire(res);
    if (res.statusCode >= 400) throw Exception(_error(res));
    return _decodeJson(res.body);
  }

  /// DELETE with a JSON body (account deletion etc.).
  static Future<Map<String, dynamic>> deleteJson(String path, Map<String, dynamic> body) async {
    final token = _shouldAttachAuth(path) ? await getToken() : null;
    final req = http.Request('DELETE', _uri(path));
    req.headers.addAll(_headers(token));
    req.body = jsonEncode(body);
    final streamed = await _client.send(req).timeout(const Duration(seconds: 30));
    await _maybeExpire(streamed);
    final res = await http.Response.fromStream(streamed);
    if (res.statusCode >= 400) throw Exception(_error(res));
    return _asMap(_decodeJson(res.body));
  }

  /// 🗑 Permanently delete the signed-in account (password re-confirm).
  static Future<Map<String, dynamic>> deleteMyAccount(String password) =>
      deleteJson('/auth/me', {'password': password});

  static Future<void> delete(String path) async {
    final token = _shouldAttachAuth(path) ? await getToken() : null;
    final res = await _client
        .delete(_uri(path), headers: _headers(token, json: false))
        .timeout(const Duration(seconds: 30));
    await _maybeExpire(res);
    if (res.statusCode >= 400) throw Exception(_error(res));
  }

  // ------------------------------------------------------ multipart (voice/files)
  static Future<Map<String, dynamic>> postMultipart(
    String path,
    List<int> bytes,
    String filename, {
    String field = 'file',
    Map<String, String> fields = const {},
  }) async {
    final token = _shouldAttachAuth(path) ? await getToken() : null;
    final req = http.MultipartRequest('POST', _uri(path));
    if (token != null) req.headers['Authorization'] = 'Bearer $token';
    req.fields.addAll(fields);
    req.files.add(http.MultipartFile.fromBytes(field, bytes, filename: filename));
    final streamed = await _client.send(req).timeout(const Duration(minutes: 3));
    await _maybeExpire(streamed);
    final res = await http.Response.fromStream(streamed);
    if (res.statusCode >= 400) throw Exception(_error(res));
    return _asMap(_decodeJson(res.body));
  }

  // ------------------------------------------------------- audio file analysis
  /// Upload an audio/music file for transcription + AI analysis (lyrics, mood,
  /// "what song is this?"). Returns transcript, analysis and conversation_id.
  static Future<Map<String, dynamic>> analyzeAudio(
    List<int> bytes,
    String filename, {
    String? prompt,
    String? conversationId,
  }) =>
      postMultipart('/files/analyze-audio', bytes, filename, fields: {
        if (prompt != null && prompt.isNotEmpty) 'prompt': prompt,
        if (conversationId != null) 'conversation_id': conversationId,
      });

  static Map<String, dynamic>? _parseSseBlock(String raw) {
    final data = <String>[];
    for (final line in raw.split(RegExp(r'\r?\n'))) {
      if (line.isEmpty || line.startsWith(':')) continue;
      final i = line.indexOf(':');
      final field = i == -1 ? line : line.substring(0, i);
      if (field != 'data') continue;
      var value = i == -1 ? '' : line.substring(i + 1);
      if (value.startsWith(' ')) value = value.substring(1);
      data.add(value);
    }
    if (data.isEmpty) return null;
    try {
      final decoded = jsonDecode(data.join('\n'));
      return decoded is Map<String, dynamic> ? decoded : null;
    } catch (_) {
      return null;
    }
  }

  // ------------------------------------------------------- SSE streaming chat
  /// Yields decoded SSE event objects from a streaming endpoint
  /// (/chat/stream, /agents/stream, /deepsearch/stream).
  static Stream<Map<String, dynamic>> streamTo(String endpoint, Map<String, dynamic> payload) async* {
    final token = _shouldAttachAuth(endpoint) ? await getToken() : null;
    final req = http.Request('POST', _uri(endpoint));
    req.headers.addAll(_headers(token));
    req.body = jsonEncode(payload);
    final res = await _client.send(req).timeout(const Duration(minutes: 6));
    await _maybeExpire(res);
    if (res.statusCode >= 400) {
      final body = await res.stream.bytesToString();
      final decoded = http.Response(body, res.statusCode);
      throw Exception(_error(decoded));
    }
    var buf = '';
    await for (final chunk in res.stream.transform(utf8.decoder)) {
      buf += chunk;
      final parts = buf.split(RegExp(r'\r?\n\r?\n'));
      buf = parts.removeLast();
      for (final raw in parts) {
        final event = _parseSseBlock(raw);
        if (event != null) yield event;
      }
    }
    if (buf.trim().isNotEmpty) {
      final event = _parseSseBlock(buf);
      if (event != null) yield event;
    }
  }

  /// Back-compat helper for the standard chat stream.
  static Stream<Map<String, dynamic>> streamChat({
    String? conversationId,
    required String message,
    List<String> files = const [],
    bool search = true,
  }) =>
      streamTo('/chat/stream', {
        'conversation_id': conversationId,
        'message': message,
        'files': files,
        'search': search,
      });
}
