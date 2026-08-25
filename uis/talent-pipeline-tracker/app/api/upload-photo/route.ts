import { promises as fs } from "node:fs";
import path from "node:path";
import { NextResponse } from "next/server";

const PROFILE_PHOTOS_DIR = path.join(process.cwd(), "imagenesPerfil");
const VALID_RECORD_ID = /^[a-zA-Z0-9-]+$/;

export const runtime = "nodejs";

export async function POST(request: Request) {
  const formData = await request.formData();
  const recordId = formData.get("recordId");
  const photo = formData.get("photo");

  if (typeof recordId !== "string" || !VALID_RECORD_ID.test(recordId)) {
    return NextResponse.json(
      { error: "recordId inválido" },
      { status: 400 },
    );
  }

  if (!(photo instanceof File) || photo.size === 0) {
    return NextResponse.json({ error: "Archivo inválido" }, { status: 400 });
  }

  await fs.mkdir(PROFILE_PHOTOS_DIR, { recursive: true });

  const photoEntries = await fs.readdir(PROFILE_PHOTOS_DIR);
  const previousPhotos = photoEntries.filter((entry) => entry.startsWith(`${recordId}.`));

  await Promise.all(
    previousPhotos.map((entry) => fs.unlink(path.join(PROFILE_PHOTOS_DIR, entry))),
  );

  const extension = path.extname(photo.name) || ".png";
  const fileName = `${recordId}${extension}`;
  const photoPath = path.join(PROFILE_PHOTOS_DIR, fileName);
  const buffer = Buffer.from(await photo.arrayBuffer());

  await fs.writeFile(photoPath, buffer);

  return NextResponse.json({
    path: `/api/profile-photo/${recordId}`,
  });
}
