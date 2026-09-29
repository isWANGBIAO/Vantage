module.exports = {
  appId: 'com.vantage.never-stop',
  productName: 'Never Stop',
  extraMetadata: { name: 'vantage-never-stop', version: '1.0.81', main: 'never-stop/main.cjs', description: 'Never Stop standalone desktop demo' },
  directories: { output: 'never-stop/release' },
  files: ['never-stop/main.cjs', 'never-stop/preload.cjs', 'never-stop/core/**/*.cjs', '!never-stop/core/**/*.test.cjs', 'never-stop/dist/**/*', 'never-stop/never_stop_execution_principles_v0_1.md', 'package.json'],
  extraResources: [],
  afterPack: null,
  npmRebuild: false,
  win: { target: ['portable'], artifactName: 'NeverStop-Demo-${version}-${arch}.${ext}' },
  portable: { requestExecutionLevel: 'user' },
};
