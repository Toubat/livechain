import { getLiveKitCredentials } from "@/lib/livekit-utils";
import { RoomServiceClient } from "livekit-server-sdk";
import { NextResponse } from "next/server";

export async function POST(request: Request) {
  try {
    const { API_KEY, API_SECRET, LIVEKIT_URL } = getLiveKitCredentials();
    const { roomName, identity, options } = await request.json();

    if (!roomName || !identity || typeof options !== "object") {
      return new NextResponse("Invalid request body", { status: 400 });
    }

    const roomService = new RoomServiceClient(LIVEKIT_URL, API_KEY, API_SECRET);
    const participant = await roomService.updateParticipant(roomName, identity, options);

    return NextResponse.json(participant);
  } catch (error) {
    return handleError(error);
  }
}

function handleError(error: unknown) {
  console.error(error);
  return new NextResponse(error instanceof Error ? error.message : "Internal server error", {
    status: 500,
  });
}
