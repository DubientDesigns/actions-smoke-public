import {
  Activity,
  Bell,
  BookOpen,
  Gauge,
  History,
  LineChart,
  Radar,
  Search,
  Settings,
  ShieldAlert,
  Sparkles,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";

export type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Delivery phase; pages from later phases render an explicit "not built yet" state. */
  phase: number;
};

export const NAV: NavItem[] = [
  { href: "/", label: "Overview", icon: Gauge, phase: 2 },
  { href: "/discoveries", label: "Live Discoveries", icon: Activity, phase: 2 },
  { href: "/tokens", label: "Token Explorer", icon: Search, phase: 2 },
  { href: "/presales", label: "Presale Radar", icon: Radar, phase: 4 },
  { href: "/influencers", label: "Influencer Intelligence", icon: Users, phase: 4 },
  { href: "/wallets", label: "Wallet Watchlist", icon: Wallet, phase: 4 },
  { href: "/security", label: "Security Analysis", icon: ShieldAlert, phase: 3 },
  { href: "/research", label: "AI Research Reports", icon: Sparkles, phase: 5 },
  { href: "/paper", label: "Paper Portfolio", icon: BookOpen, phase: 6 },
  { href: "/performance", label: "Historical Performance", icon: History, phase: 6 },
  { href: "/alerts", label: "Alerts", icon: Bell, phase: 5 },
  { href: "/system", label: "Data Sources & Health", icon: LineChart, phase: 2 },
  { href: "/settings", label: "Settings", icon: Settings, phase: 2 },
];

export const CURRENT_PHASE = 2;

export const CHAIN_LABEL: Record<string, string> = {
  bsc: "BNB",
  ethereum: "ETH",
  solana: "SOL",
  base: "BASE",
};

export const CHAIN_BY_ID: Record<number, string> = { 1: "bsc", 2: "ethereum", 3: "solana", 4: "base" };

export const EXPLORER: Record<string, { token: (a: string) => string }> = {
  bsc: { token: (a) => `https://bscscan.com/token/${a}` },
  ethereum: { token: (a) => `https://etherscan.io/token/${a}` },
  solana: { token: (a) => `https://solscan.io/token/${a}` },
  base: { token: (a) => `https://basescan.org/token/${a}` },
};
