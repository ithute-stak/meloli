import type { Metadata } from "next";
import "./globals.css";
import PwaRegistration from "./components/PwaRegistration";
import PwaInstallPrompt from "./components/PwaInstallPrompt";

export const metadata: Metadata = {
  title: "Meloli Airwaves | Advertise with confidence",
  description: "Submit, pay, approve and manage advertising campaigns with Meloli Airwaves Media.",
  manifest: "/manifest.webmanifest",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body><PwaRegistration/><PwaInstallPrompt/>{children}</body></html>;
}
