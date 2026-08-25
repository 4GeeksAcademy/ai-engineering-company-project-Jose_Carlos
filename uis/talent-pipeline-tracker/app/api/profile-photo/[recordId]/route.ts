import { promises as fs } from "node:fs";
import path from "node:path";
import { NextResponse } from "next/server";

const PROFILE_PHOTOS_DIR = path.join(process.cwd(), "imagenesPerfil");
const DEFAULT_PHOTO_PATH = path.join(PROFILE_PHOTOS_DIR, "imagenPerfil.png");
const VALID_RECORD_ID = /^[a-zA-Z0-9-]+$/;

type RouteContext = {
  params: Promise<{ recordId: string }>;
};

export const runtime = "nodejs";

function getContentType(filePath: string): string {
  const extension = path.extname(filePath).toLowerCase();
  if (extension === ".jpg" || extension === ".jpeg") return "image/jpeg";
  if (extension === ".webp") return "image/webp";
  if (extension === ".gif") return "image/gif";
  if (extension === ".svg") return "image/svg+xml";
  return "image/png";
}

export async function GET(_: Request, context: RouteContext) {
  const { recordId } = await context.params;

  if (!VALID_RECORD_ID.test(recordId)) {
    return NextResponse.json({ error: "recordId inválido" }, { status: 400 });
  }

  let targetPhotoPath = DEFAULT_PHOTO_PATH;

  try {
    const files = await fs.readdir(PROFILE_PHOTOS_DIR);
    const matchedPhoto = files.find((fileName) => fileName.startsWith(`${recordId}.`));
    if (matchedPhoto) {
      targetPhotoPath = path.join(PROFILE_PHOTOS_DIR, matchedPhoto);
    }
  } catch (error) {
    const isMissingDir =
      typeof error === "object" &&
      error !== null &&
      "code" in error &&
      error.code === "ENOENT";
    if (!isMissingDir) {
      return NextResponse.json(
        {
          error:
            error instanceof Error
              ? error.message
              : "No se pudo leer el directorio de fotos",
        },
        { status: 500 },
      );
    }
  }

  try {
    const fileBuffer = await fs.readFile(targetPhotoPath);
    return new NextResponse(fileBuffer, {
      headers: {
        "Content-Type": getContentType(targetPhotoPath),
        "Cache-Control": "no-store",
      },
    });
  } catch (error) {
    if (targetPhotoPath !== DEFAULT_PHOTO_PATH) {
      const defaultPhoto = await fs.readFile(DEFAULT_PHOTO_PATH);
      return new NextResponse(defaultPhoto, {
        headers: {
          "Content-Type": "image/png",
          "Cache-Control": "no-store",
        },
      });
    }

    return NextResponse.json(
      {
        error:
          error instanceof Error
            ? error.message
            : "No se pudo servir la imagen",
      },
      { status: 500 },
    );
  }
}
