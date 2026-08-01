import { Badge } from "@/components/ui/badge";

export function ActionBadge({ action }: { action: string }) {
  if (action === "BUY") return <Badge variant="success">BUY</Badge>;
  if (action === "SELL") return <Badge variant="destructive">SELL</Badge>;
  return <Badge variant="secondary">WATCH</Badge>;
}
