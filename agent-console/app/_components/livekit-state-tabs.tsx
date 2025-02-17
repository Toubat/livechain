import { ObservableWrapper } from "@/components/observable-wrapper";
import { Badge } from "@/components/ui/badge";
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useLivekitState } from "@/hooks/use-livekit";
import { cn, withExcludedKeys, withIncludedKeys } from "@/lib/utils";
import { useRemoteParticipants } from "@livekit/components-react";
import { House, UserRound, UsersRound, Video } from "lucide-react";
import { ParticipantTrackViewer } from "./participant-track-viewer";
import { ParticipantViewer } from "./participant-viewer";
import { RemoteParticipantsViewer } from "./remote-participants-viewer";
import { RoomStateViewer } from "./room-state-viewer";
import { VideoConference } from "./video-conference";
export interface LivekitStateTabsProps {
  defaultValue?: string;
  className?: string;
}

export type TabValue = "room" | "local-participant" | "remote-participants" | "videos";

export type TabItem = {
  label: string;
  value: TabValue;
  icon: React.ReactNode;
  indicator?: React.ReactNode;
};

const RemoteParticipantsIndicator = () => {
  const pc = useRemoteParticipants();
  return (
    <Badge className="ms-1.5 min-w-5 bg-primary/15" variant="secondary">
      {pc.length}
    </Badge>
  );
};

const iconProps = {
  className: "-ms-0.5 me-1.5 opacity-60",
  size: 16,
  strokeWidth: 2,
};

const tabItems: TabItem[] = [
  {
    label: "Room",
    value: "room",
    icon: <House {...iconProps} />,
  },
  {
    label: "Local Participant",
    value: "local-participant",
    icon: <UserRound {...iconProps} />,
  },
  {
    label: "Remote Participants",
    value: "remote-participants",
    icon: <UsersRound {...iconProps} />,
    indicator: <RemoteParticipantsIndicator />,
  },
  {
    label: "Videos",
    value: "videos",
    icon: <Video {...iconProps} />,
  },
];

const LivekitStateContent = ({
  value,
  children,
}: {
  value: TabValue;
  children: React.ReactNode;
}) => {
  return (
    <TabsContent value={value} className="flex-1 relative p-0 m-0">
      <div className="absolute inset-0">
        <ScrollArea className="h-full">
          <div className="py-4 flex flex-col gap-4">{children}</div>
        </ScrollArea>
      </div>
    </TabsContent>
  );
};

export const LivekitStateTabs = ({ defaultValue = "room", className }: LivekitStateTabsProps) => {
  const { room, localParticipant } = useLivekitState();

  return (
    <Tabs defaultValue={defaultValue} className={cn("h-full flex flex-col", className)}>
      <ScrollArea>
        <TabsList className="h-auto gap-2 rounded-none border-b border-border bg-transparent px-0 text-foreground w-full flex">
          {tabItems.map((item) => (
            <TabsTrigger
              key={item.value}
              value={item.value}
              className="flex-1 relative after:absolute after:inset-x-0 after:bottom-0 after:-mb-1 after:h-0.5 hover:bg-accent hover:text-foreground data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:after:bg-primary data-[state=active]:hover:bg-accent"
            >
              {item.icon}
              {item.label}
              {item.indicator}
            </TabsTrigger>
          ))}
        </TabsList>
        <ScrollBar orientation="horizontal" />
      </ScrollArea>
      <LivekitStateContent value="room">
        <ObservableWrapper state={room} title="Room State" subtitle={room.name || "Not connected"}>
          {(state) => <RoomStateViewer {...state} />}
        </ObservableWrapper>
      </LivekitStateContent>
      <LivekitStateContent value="local-participant">
        <ObservableWrapper
          state={withExcludedKeys(localParticipant, ["tracks"])}
          title="Participant State"
          subtitle={localParticipant.identity}
        >
          {(state) => <ParticipantViewer {...state} />}
        </ObservableWrapper>
        <ObservableWrapper
          state={withIncludedKeys(localParticipant, ["tracks"])}
          title="Participant Tracks"
          subtitle={localParticipant.identity}
        >
          {(state) => <ParticipantTrackViewer {...state} />}
        </ObservableWrapper>
      </LivekitStateContent>
      <LivekitStateContent value="remote-participants">
        <RemoteParticipantsViewer />
      </LivekitStateContent>
      <LivekitStateContent value="videos">
        <VideoConference />
      </LivekitStateContent>
    </Tabs>
  );
};
