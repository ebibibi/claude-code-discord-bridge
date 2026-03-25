using './main.bicep'

// デプロイ時に値を指定する
// az deployment group create -g <rg> -f main.bicep -p main.bicepparam
param env = 'dev'
param aiFoundryEndpoint = readEnvironmentVariable('AZURE_AI_FOUNDRY_ENDPOINT', '')
param entraClientId = readEnvironmentVariable('ENTRA_CLIENT_ID', '466f4cad-0000-0000-0000-000000000000')
