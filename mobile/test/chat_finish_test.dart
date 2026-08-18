import 'package:flutter_test/flutter_test.dart';
import 'package:mood_ai_mobile/chat_models.dart';

void main() {
  group('mediaFilename', () {
    test('slugs the prompt and picks the right extension', () {
      expect(mediaFilename('a red kite at dusk', 'image'), 'chatmood-a-red-kite-at-dusk.png');
      expect(mediaFilename('Night Drive!!', 'video'), 'chatmood-night-drive.mp4');
    });

    test('falls back when the prompt is empty', () {
      expect(mediaFilename(null, 'image'), 'chatmood-image.png');
      expect(mediaFilename('   ', 'video'), 'chatmood-video.mp4');
    });
  });

  group('ChatMedia.fromMeta', () {
    test('carries file_id so manage actions can light up without a reload', () {
      final media = ChatMedia.fromMeta({
        'media': [
          {
            'kind': 'image',
            'url': 'https://cdn.example/x.png',
            'prompt': 'a red kite',
            'stored': 'r2',
            'file_id': 'file-123',
          },
        ],
      });
      expect(media, isNotNull);
      expect(media!.fileId, 'file-123');
      expect(media.manageable, isTrue);
      expect(media.kind, 'image');
      expect(media.stored, 'r2');
    });

    test('empty file_id hides manage actions (fail-open hotlink)', () {
      final media = ChatMedia.fromMeta({
        'media': [
          {'kind': 'video', 'url': 'https://hot.link/v.mp4', 'file_id': ''},
        ],
      });
      expect(media, isNotNull);
      expect(media!.fileId, isNull);
      expect(media.manageable, isFalse);
    });

    test('missing or empty media returns null', () {
      expect(ChatMedia.fromMeta(null), isNull);
      expect(ChatMedia.fromMeta({'media': []}), isNull);
      expect(ChatMedia.fromMeta({'mode': 'chat'}), isNull);
    });
  });
}
