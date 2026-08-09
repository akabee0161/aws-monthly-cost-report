module.exports = {
  testEnvironment: "node",
  roots: ["<rootDir>/test"],
  testMatch: ["**/*.test.ts"],
  // `npm run build` は lib/*.js をソースと同じ場所に出力する。既定の解決順では
  // その古い .js が .ts より優先され、テストがビルド当時のコードを検証してしまう。
  moduleFileExtensions: ["ts", "tsx", "js", "jsx", "json", "node"],
  transform: {
    "^.+\\.tsx?$": "ts-jest",
  },
};
