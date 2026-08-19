import { ChevronDown } from "lucide-react";

/**
 * ❓ Landing FAQ — "best questions, straight answers".
 *
 * Native <details>/<summary> accordion: server-rendered (zero client JS),
 * keyboard- and screen-reader-accessible for free. FAQ_ITEMS is also the
 * source of the FAQPage JSON-LD emitted by app/page.tsx, so search engines
 * see exactly the copy visitors read — keep them honest and in sync.
 */
export const FAQ_ITEMS: [string, string][] = [
  [
    "What is ChatMood?",
    "ChatMood is one AI workspace for everything: streaming chat with a sharp personality, deep research with live citations, image generation, short films with AI voiceovers, and real-time voice conversations — all under one account.",
  ],
  [
    "Is ChatMood free?",
    "Yes. The free plan covers everyday chat, research and daily image and video generations. Pro lifts the ceilings — much higher daily limits, watermark-free 1080p renders, longer memory retention and faster rate limits.",
  ],
  [
    "Which AI models power ChatMood?",
    "ChatMood orchestrates frontier models rather than betting on one: Grok-class reasoning from xAI by default, with GPT and Gemini joining Arena debates and standing in automatically if a provider is ever down.",
  ],
  [
    "Can ChatMood search the live web?",
    "Yes — answers can be grounded in real-time web, X and news sources with citations you can check. DeepSearch goes further, running multi-round investigations with sources saved to your library.",
  ],
  [
    "Can I create images and videos with ChatMood?",
    "Absolutely. Generate images right in chat, and direct short films with AI voiceovers, music and optional subtitles. Free generations refresh daily, and Pro renders export clean without the watermark.",
  ],
  [
    "Does ChatMood remember past conversations?",
    "It can. Long-term memory keeps what you choose to share — topics, preferences, what earlier chats were about — so you never re-explain. Memory is always visible, editable and wipeable from Settings.",
  ],
  [
    "Is there a ChatMood mobile app?",
    "The Android app is available as a direct APK today (Google Play listing is in review), complete with push notifications for Arena verdicts and full voice mode. Or simply open the site on your phone — it's fully mobile-friendly.",
  ],
  [
    "How do I pay for ChatMood Pro?",
    "Mobile money first: send MTN, Telecel or Vodafone MoMo to the published number, submit your transaction ID, and your plan activates as soon as it's verified — no card needed. Stripe card payments slot in alongside.",
  ],
  [
    "Is my data private?",
    "Your conversations, files, memory and settings belong to your account alone. You can export or permanently delete everything — chats, memory, files and the account itself — from Settings at any time.",
  ],
];

export default function LandingFaq() {
  return (
    <section id="faq" className="border-t border-line px-4 py-16 sm:px-6 sm:py-20">
      <div className="mx-auto max-w-3xl">
        <h2 className="text-center text-xl font-semibold">Frequently asked questions</h2>
        <p className="mt-2 text-center text-sm text-gray-500">The best questions — with straight answers.</p>
        <div className="mt-10 space-y-3">
          {FAQ_ITEMS.map(([question, answer]) => (
            <details key={question} className="group rounded-2xl bg-composer open:bg-white/[0.07]">
              <summary className="flex cursor-pointer select-none list-none items-center justify-between gap-4 px-5 py-4 text-sm font-medium text-gray-100 [&::-webkit-details-marker]:hidden">
                {question}
                <ChevronDown
                  aria-hidden
                  className="h-4 w-4 shrink-0 text-gray-500 transition-transform duration-200 group-open:rotate-180"
                />
              </summary>
              <p className="px-5 pb-5 text-sm leading-relaxed text-gray-400">{answer}</p>
            </details>
          ))}
        </div>
        <p className="mt-8 text-center text-sm text-gray-500">
          Still curious?{" "}
          <a href="/signup" className="text-gray-300 underline underline-offset-4 transition hover:text-white">
            Create a free account
          </a>{" "}
          and just ask.
        </p>
      </div>
    </section>
  );
}
