import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ChevronDown } from "lucide-react";

export const CollapsibleSection = ({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) => (
  <Collapsible defaultOpen>
    <CollapsibleTrigger className="w-full flex items-center justify-between p-2 bg-muted/50 rounded-md">
      <span className="text-sm font-medium">{title}</span>
      <ChevronDown className="h-4 w-4 transition-transform [&[data-state=open]]:rotate-180" />
    </CollapsibleTrigger>
    <CollapsibleContent className="pt-2">{children}</CollapsibleContent>
  </Collapsible>
);
