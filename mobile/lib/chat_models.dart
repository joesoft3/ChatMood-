/// Shared chat-finish models used by the Flutter chat screen and its tests.
/// Kept free of plugin imports so `fromMeta` / `mediaFilename` stay unit-testable.

/// 🎨🎬 In-chat creation: image/video generated inline from the chat box.
class ChatMedia {
  ChatMedia({
    required this.kind,
    this.url,
    this.prompt,
    this.stored,
    this.fileId,
    this.pending = false,
    this.stage,
    this.done,
    this.total,
  });

  final String kind; // 'image' | 'video'
  String? url;
  String? prompt;
  String? stored; // r2 | local | hotlink
  /// FileAsset id — present once the generation is archived. Enables the
  /// stable download route plus edit/delete; absent for provider hotlinks.
  String? fileId;
  bool pending;
  String? stage; // scenes | compositing
  int? done;
  int? total;

  bool get manageable => fileId != null && fileId!.isNotEmpty;

  /// Reload contract: assistant meta.media[0] re-renders the artifact.
  static ChatMedia? fromMeta(dynamic meta) {
    if (meta is! Map) return null;
    final list = meta['media'];
    if (list is! List || list.isEmpty || list.first is! Map) return null;
    final m = Map<dynamic, dynamic>.from(list.first as Map);
    final rawId = '${m['file_id'] ?? ''}';
    return ChatMedia(
      kind: '${m['kind'] ?? 'image'}',
      url: m['url'] as String?,
      prompt: m['prompt'] as String?,
      stored: m['stored'] as String?,
      fileId: rawId.isEmpty ? null : rawId,
    );
  }
}

/// A filesystem-safe name from the prompt: "a red kite" → chatmood-a-red-kite.png
String mediaFilename(String? prompt, String kind) {
  final slug = (prompt ?? kind)
      .toLowerCase()
      .replaceAll(RegExp(r'[^a-z0-9]+'), '-')
      .replaceAll(RegExp(r'^-+|-+$'), '');
  final clipped = slug.isEmpty ? kind : (slug.length > 48 ? slug.substring(0, 48) : slug);
  return 'chatmood-$clipped.${kind == 'image' ? 'png' : 'mp4'}';
}
