"use client";

import { useEffect, useRef } from "react";

/**
 * 🎬 Ambient hero video — the generated /hero-ambient.mp4 loop that backdrops
 * the landing hero. Decorative (aria-hidden): muted, inline, auto-looping,
 * with the JPEG poster painted instantly while the stream warms up.
 *
 * Respects prefers-reduced-motion: pause the loop for users who asked the OS
 * to keep things still — the static poster frame remains as the backdrop.
 */
export default function HeroVideo() {
  const ref = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const video = ref.current;
    if (!video) return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => {
      if (mq.matches) video.pause();
      else video.play().catch(() => undefined); // autoplay blocked → poster stays
    };
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  return (
    <video
      ref={ref}
      aria-hidden="true"
      tabIndex={-1}
      className="absolute inset-0 h-full w-full object-cover"
      autoPlay
      muted
      loop
      playsInline
      preload="auto"
      poster="/hero-ambient.jpg"
    >
      <source src="/hero-ambient.mp4" type="video/mp4" />
    </video>
  );
}
