import type { Config } from "jest";
import nextJest from "next/jest.js";

const createJestConfig = nextJest({
  // Raíz de la app Next.js: carga next.config.ts y los .env en el entorno de pruebas.
  dir: "./",
});

const config: Config = {
  coverageProvider: "v8",
  testEnvironment: "jsdom",
  testMatch: ["<rootDir>/__tests__/**/*.test.ts"],
  // La cobertura se mide sobre las utilidades del frontend: auth (AUTH-088), api y constants (FE-019).
  collectCoverageFrom: ["app/lib/**/*.ts"],
};

export default createJestConfig(config);
