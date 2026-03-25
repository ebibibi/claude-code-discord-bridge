// JBS AI 業務支援ツール — Azure リソース定義
// SWA (React SPA) + Functions (Python API) + Storage Account

targetScope = 'resourceGroup'

@description('デプロイ先リージョン')
param location string = 'japaneast'

@description('環境名（dev / prod）')
@allowed(['dev', 'prod'])
param env string = 'dev'

@description('Azure AI Foundry エンドポイント URL')
param aiFoundryEndpoint string

@description('Entra ID アプリケーション（クライアント）ID')
param entraClientId string

@description('Entra ID テナント ID')
param entraTenantId string = 'cc7dee35-6e31-4e44-851e-52ba57be81c4'

// -------------------------------------------------------------------
// 命名規則
// -------------------------------------------------------------------
var baseName = 'jbs-ai-tools'
var suffix = env == 'prod' ? '' : '-${env}'
var storageAccountName = replace('staitools${env}', '-', '')
var functionAppName = '${baseName}-api${suffix}'
var hostingPlanName = '${baseName}-plan${suffix}'
var swaName = '${baseName}-web${suffix}'
var appInsightsName = '${baseName}-insights${suffix}'

// -------------------------------------------------------------------
// Storage Account（Blob + Table）
// -------------------------------------------------------------------
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
}

resource uploadsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'uploads'
}

resource resultsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'results'
}

resource templatesContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'templates'
}

// -------------------------------------------------------------------
// Application Insights
// -------------------------------------------------------------------
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    RetentionInDays: 30
  }
}

// -------------------------------------------------------------------
// App Service Plan（Consumption = Y1）
// -------------------------------------------------------------------
resource hostingPlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: hostingPlanName
  location: location
  kind: 'functionapp'
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
  }
}

// -------------------------------------------------------------------
// Azure Functions（Python API）
// -------------------------------------------------------------------
resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: hostingPlan.id
    httpsOnly: true
    siteConfig: {
      pythonVersion: '3.11'
      linuxFxVersion: 'PYTHON|3.11'
      cors: {
        allowedOrigins: [
          'https://${swaName}.azurestaticapps.net'
        ]
      }
      appSettings: [
        { name: 'AzureWebJobsStorage', value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};EndpointSuffix=core.windows.net;AccountKey=${storageAccount.listKeys().keys[0].value}' }
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'APPINSIGHTS_INSTRUMENTATIONKEY', value: appInsights.properties.InstrumentationKey }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
        { name: 'AZURE_AI_FOUNDRY_ENDPOINT', value: aiFoundryEndpoint }
        { name: 'AZURE_STORAGE_CONNECTION_STRING', value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};EndpointSuffix=core.windows.net;AccountKey=${storageAccount.listKeys().keys[0].value}' }
      ]
    }
  }
}

// -------------------------------------------------------------------
// Static Web App（React SPA + Entra ID認証）
// -------------------------------------------------------------------
resource staticWebApp 'Microsoft.Web/staticSites@2023-12-01' = {
  name: swaName
  location: location
  sku: {
    name: 'Standard'
    tier: 'Standard'
  }
  properties: {}
}

// SWA → Functions のバックエンドリンク
resource swaBackend 'Microsoft.Web/staticSites/linkedBackends@2023-12-01' = {
  parent: staticWebApp
  name: 'api-backend'
  properties: {
    backendResourceId: functionApp.id
    region: location
  }
}

// -------------------------------------------------------------------
// RBAC: Functions の Managed Identity に Storage アクセスを付与
// -------------------------------------------------------------------
var storageBlobDataContributorRole = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var storageTableDataContributorRole = '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'

resource blobRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storageAccount
  name: guid(storageAccount.id, functionApp.id, storageBlobDataContributorRole)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRole)
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource tableRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storageAccount
  name: guid(storageAccount.id, functionApp.id, storageTableDataContributorRole)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageTableDataContributorRole)
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// -------------------------------------------------------------------
// Outputs
// -------------------------------------------------------------------
output functionAppName string = functionApp.name
output functionAppHostname string = functionApp.properties.defaultHostName
output staticWebAppName string = staticWebApp.name
output staticWebAppUrl string = 'https://${staticWebApp.properties.defaultHostname}'
output storageAccountName string = storageAccount.name
output functionAppPrincipalId string = functionApp.identity.principalId
