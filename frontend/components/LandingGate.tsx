"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { token } from "@/lib/api";

/** Logged-in visitors skip the marketing page and land on the chat home. */
export default function LandingGate() {
  const router = useRouter();
  useEffect(() => {
    if (token.get()) router.replace("/chat");
  }, [router]);
  return null;
}
