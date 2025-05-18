/**
 * Copyright 2024 Amazon.com and its affiliates; all rights reserved.
 * This file is AWS Content and may not be duplicated or distributed without permission
 * 
 * This module contains a helper class for building and using Agents for Amazon Bedrock.
 * The AgentsForAmazonBedrock class provides a convenient interface for working with Agents.
 * It includes methods for creating, updating, and invoking Agents, as well as managing
 * IAM roles and Lambda functions for action groups.
 * 
 * Here is a quick example of using the class:
 * 
 *     const { AgentsForAmazonBedrock } = require('./bedrock_agent_helper');
 *     const agents = new AgentsForAmazonBedrock();
 *     const name = "my_agent";
 *     const descr = "my agent description";
 *     const instructions = "you are an agent that ...";
 *     const model_id = "...haiku...";
 *     const agent_id = await agents.createAgent(name, descr, instructions, model_id);
 *     
 *     const action_group_name = "my_action_group";
 *     const action_group_descr = "my action group description";
 *     const lambda_code = "my_lambda.js";
 *     const function_defs = [{ ... }];
 *     const action_group_arn = await agents.addActionGroupWithLambda(agent_id,
 *                                      lambda_function_name, lambda_code, 
 *                                      function_defs, action_group_name, action_group_descr);
 *     await agents.simpleAgentInvoke("when's my next payment due?", agent_id);
 * 
 * Here is a summary of the most important methods:
 * 
 * - createAgent: Creates a new Agent.
 * - addActionGroupWithLambda: Creates a new Action Group for an Agent, backed by Lambda.
 */

const { 
  BedrockAgentClient, 
  ListAgentsCommand, 
  GetAgentCommand, 
  ListAgentAliasesCommand, 
  GetAgentAliasCommand,
  CreateAgentCommand,
  PrepareAgentCommand,
  AssociateAgentKnowledgeBaseCommand,
  DeleteAgentCommand,
  DeleteAgentAliasCommand,
  CreateAgentAliasCommand,
  AssociateAgentCollaboratorCommand
} = require('@aws-sdk/client-bedrock-agent');

const { 
  BedrockAgentRuntimeClient 
} = require('@aws-sdk/client-bedrock-agent-runtime');

const { 
  IAMClient, 
  CreateRoleCommand, 
  GetRoleCommand, 
  AttachRolePolicyCommand, 
  PutRolePolicyCommand,
  DetachRolePolicyCommand,
  DeleteRoleCommand,
  DeleteRolePolicyCommand
} = require('@aws-sdk/client-iam');

const { 
  LambdaClient, 
  CreateFunctionCommand, 
  AddPermissionCommand, 
  GetFunctionCommand, 
  DeleteFunctionCommand 
} = require('@aws-sdk/client-lambda');

const { 
  S3Client 
} = require('@aws-sdk/client-s3');

const { 
  DynamoDBClient 
} = require('@aws-sdk/client-dynamodb');

const { 
  DynamoDBDocumentClient 
} = require('@aws-sdk/lib-dynamodb');

const { 
  STSClient, 
  GetCallerIdentityCommand 
} = require('@aws-sdk/client-sts');

const fs = require('fs');
const path = require('path');
const { promisify } = require('util');
const { v4: uuidv4 } = require('uuid');
const { createReadStream } = require('fs');
const { createGzip } = require('zlib');
const { pipeline } = require('stream');
const archiver = require('archiver');
const chalk = require('chalk');

// Constants
const PYTHON_TIMEOUT = 180;
const PYTHON_RUNTIME = "nodejs18.x";
const DEFAULT_ALIAS = "TSTALIASID";
const DEFAULT_CI_ACTION_GROUP_NAME = "CodeInterpreterAction";
const UNDECIDABLE_CLASSIFICATION = "undecidable";
const ROUTER_MODEL = "us.anthropic.claude-3-haiku-20240307-v1:0";
const TRACE_TRUNCATION_LENGTH = 300;

// Default IAM role and policies
const DEFAULT_AGENT_IAM_ROLE_NAME = "DEFAULT_AgentExecutionRole";
const DEFAULT_AGENT_IAM_ASSUME_ROLE_POLICY = {
  Version: "2012-10-17",
  Statement: [
    {
      Sid: "AllowBedrock",
      Effect: "Allow",
      Principal: {
        Service: "bedrock.amazonaws.com"
      },
      Action: "sts:AssumeRole"
    }
  ]
};

const DEFAULT_AGENT_IAM_POLICY = {
  Version: "2012-10-17",
  Statement: [
    {
      Sid: "AmazonBedrockAgentInferencProfilePolicy1",
      Effect: "Allow",
      Action: [
        "bedrock:InvokeModel*",
        "bedrock:CreateInferenceProfile"
      ],
      Resource: [
        "arn:aws:bedrock:*::foundation-model/*",
        "arn:aws:bedrock:*:*:inference-profile/*",
        "arn:aws:bedrock:*:*:application-inference-profile/*",
      ],
    },
    {
      Sid: "AmazonBedrockAgentInferencProfilePolicy2",
      Effect: "Allow",
      Action: [
        "bedrock:GetInferenceProfile",
        "bedrock:ListInferenceProfiles",
        "bedrock:DeleteInferenceProfile",
        "bedrock:TagResource",
        "bedrock:UntagResource",
        "bedrock:ListTagsForResource"
      ],
      Resource: [
        "arn:aws:bedrock:*:*:inference-profile/*",
        "arn:aws:bedrock:*:*:application-inference-profile/*"
      ]
    },
    {
      Sid: "AmazonBedrockAgentBedrockFoundationModelPolicy",
      Effect: "Allow",
      Action: [
        "bedrock:GetAgentAlias",
        "bedrock:InvokeAgent"
      ],
      Resource: [
        "arn:aws:bedrock:*:*:agent/*",
        "arn:aws:bedrock:*:*:agent-alias/*"
      ]
    },
    {
      Sid: "AmazonBedrockAgentBedrockInvokeGuardrailModelPolicy",
      Effect: "Allow",
      Action: [
        "bedrock:InvokeModel",
        "bedrock:GetGuardrail",
        "bedrock:ApplyGuardrail"
      ],
      Resource: "arn:aws:bedrock:*:*:guardrail/*"
    },
    {
      Sid: "QueryKB",
      Effect: "Allow",
      Action: [
        "bedrock:Retrieve",
        "bedrock:RetrieveAndGenerate"
      ],
      Resource: "arn:aws:bedrock:*:*:knowledge-base/*"
    }
  ]
};

/**
 * Provides an easy to use wrapper for Agents for Amazon Bedrock.
 */
class AgentsForAmazonBedrock {
  /**
   * Constructs an instance.
   */
  constructor() {
    this._region = process.env.AWS_REGION || 'us-east-1';
    
    // Initialize clients
    this._stsClient = new STSClient({ region: this._region });
    this._iamClient = new IAMClient({ region: this._region });
    this._lambdaClient = new LambdaClient({ region: this._region });
    this._s3Client = new S3Client({ region: this._region });
    this._dynamodbClient = new DynamoDBClient({ region: this._region });
    this._dynamodbDocClient = DynamoDBDocumentClient.from(this._dynamodbClient);
    
    this._bedrockAgentClient = new BedrockAgentClient({ 
      region: this._region 
    });
    
    this._bedrockAgentRuntimeClient = new BedrockAgentRuntimeClient({ 
      region: this._region,
      // Configure for long invocations
      requestHandler: {
        timeoutInMs: 600000 // 10 minutes
      }
    });
    
    // Initialize account ID asynchronously
    this._accountIdPromise = this._initializeAccountId();
  }

  /**
   * Initialize the account ID
   * @private
   */
  async _initializeAccountId() {
    try {
      const response = await this._stsClient.send(new GetCallerIdentityCommand({}));
      this._accountId = response.Account;
      this._suffix = `${this._region}-${this._accountId}`;
      return this._accountId;
    } catch (error) {
      console.error("Error getting caller identity:", error);
      throw error;
    }
  }

  /**
   * Ensures the account ID is initialized before proceeding
   * @private
   */
  async _ensureAccountId() {
    if (!this._accountId) {
      await this._accountIdPromise;
    }
    return this._accountId;
  }

  /**
   * Returns the region for this instance.
   * @returns {string} The AWS region
   */
  getRegion() {
    return this._region;
  }
  
  /**
   * Creates an IAM role for a Lambda function built to implement an Action Group for an Agent.
   * 
   * @param {string} agentName - Name of the agent for which this Lambda supports
   * @param {Object} additionalFunctionIamPolicy - Additional IAM policy to be attached to the role
   * @param {Array<string>} subAgentArns - List of sub-agent ARNs to allow this Lambda to invoke
   * @param {string} dynamodbTableName - Name of the DynamoDB table to that can be accessed by this Lambda
   * @param {boolean} enableTrace - Whether to print out the ARN of the new role
   * @returns {Promise<string>} ARN of the new IAM role
   * @private
   */
  async _createLambdaIamRole(
    agentName, 
    additionalFunctionIamPolicy = null, 
    subAgentArns = null, 
    dynamodbTableName = null, 
    enableTrace = false
  ) {
    await this._ensureAccountId();
    
    const lambdaFunctionRoleName = `${agentName}-lambda-role-${this._suffix}`;
    const dynamodbAccessPolicyName = `${agentName}-dynamodb-policy`;
    
    // Create IAM Role for the Lambda function
    let lambdaIamRole;
    try {
      const assumeRolePolicyDocument = {
        Version: "2012-10-17",
        Statement: [
          {
            Effect: "Allow",
            Principal: {
              Service: "lambda.amazonaws.com"
            },
            Action: "sts:AssumeRole"
          }
        ]
      };
      
      const createRoleParams = {
        RoleName: lambdaFunctionRoleName,
        AssumeRolePolicyDocument: JSON.stringify(assumeRolePolicyDocument)
      };
      
      const createRoleResponse = await this._iamClient.send(new CreateRoleCommand(createRoleParams));
      lambdaIamRole = createRoleResponse;
      
      // Pause to make sure role is created
      await new Promise(resolve => setTimeout(resolve, 10000));
    } catch (error) {
      // If role already exists, get it
      const getRoleParams = {
        RoleName: lambdaFunctionRoleName
      };
      
      lambdaIamRole = await this._iamClient.send(new GetRoleCommand(getRoleParams));
    }
    
    // Attach Lambda basic execution policy to the role
    await this._iamClient.send(new AttachRolePolicyCommand({
      RoleName: lambdaFunctionRoleName,
      PolicyArn: 'arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole'
    }));
    
    // If an additional IAM policy has been provided, attach it to the role as well
    if (additionalFunctionIamPolicy) {
      if (enableTrace) {
        console.log(`Attaching additional IAM policy to Lambda role:\n${JSON.stringify(additionalFunctionIamPolicy, null, 2)}`);
      }
      
      await this._iamClient.send(new PutRolePolicyCommand({
        PolicyDocument: JSON.stringify(additionalFunctionIamPolicy),
        PolicyName: "additional_function_policy",
        RoleName: lambdaFunctionRoleName
      }));
    }
    
    // Create a policy to allow Lambda to invoke sub-agents
    if (subAgentArns) {
      const tmpResources = subAgentArns.map(subAgentArn => 
        subAgentArn.replace(":agent/", ":agent*/") + "*"
      );
      
      const subAgentPolicyDocument = {
        Version: "2012-10-17",
        Statement: [
          {
            Sid: "AmazonBedrockAgentInvokeSubAgentPolicy",
            Effect: "Allow",
            Action: ["bedrock:InvokeAgent", "bedrock:GetAgentAlias"],
            Resource: tmpResources
          },
          {
            Sid: "AmazonBedrockAgentGetAgentPolicy",
            Effect: "Allow",
            Action: "bedrock:GetAgent",
            Resource: subAgentArns
          }
        ]
      };
      
      // Attach the inline policy to the Lambda function's role
      await this._iamClient.send(new PutRolePolicyCommand({
        PolicyDocument: JSON.stringify(subAgentPolicyDocument),
        PolicyName: "sub_agent_policy",
        RoleName: lambdaFunctionRoleName
      }));
    }
    
    // Create a policy to grant access to the DynamoDB table
    if (dynamodbTableName) {
      const dynamodbAccessPolicy = {
        Version: "2012-10-17",
        Statement: [
          {
            Effect: "Allow",
            Action: [
              "dynamodb:GetItem",
              "dynamodb:PutItem",
              "dynamodb:DeleteItem",
              "dynamodb:Query",
              "dynamodb:UpdateItem"
            ],
            Resource: `arn:aws:dynamodb:${this._region}:${this._accountId}:table/${dynamodbTableName}`
          }
        ]
      };
      
      // Attach the inline policy to the Lambda function's role
      await this._iamClient.send(new PutRolePolicyCommand({
        PolicyDocument: JSON.stringify(dynamodbAccessPolicy),
        PolicyName: dynamodbAccessPolicyName,
        RoleName: lambdaFunctionRoleName
      }));
    }
    
    return lambdaIamRole.Role.Arn;
  }
  
  /**
   * Gets the latest alias ID for the specified Agent.
   * 
   * @param {string} agentId - Id of the agent for which to get the latest alias ID
   * @param {boolean} verbose - Whether to print verbose output
   * @returns {Promise<string>} Latest alias ID
   */
  async getAgentLatestAliasId(agentId, verbose = false) {
    const listAliasesParams = {
      agentId: agentId,
      maxResults: 100
    };
    
    const agentAliases = await this._bedrockAgentClient.send(
      new ListAgentAliasesCommand(listAliasesParams)
    );
    
    let latestAliasId = "";
    let latestUpdate = new Date(0); // 1970-01-01
    
    for (const summary of agentAliases.agentAliasSummaries) {
      const currUpdate = new Date(summary.updatedAt);
      if (currUpdate > latestUpdate) {
        latestAliasId = summary.agentAliasId;
        await this.waitAgentAliasStatusUpdate(agentId, latestAliasId, false);
        latestUpdate = currUpdate;
        const aliasName = summary.agentAliasName;
        
        if (verbose) {
          console.log(`for id: ${agentId}, picked latest alias: ${latestAliasId}`);
          console.log(`  updated at: ${latestUpdate}`);
          console.log(`  alias name: ${aliasName}\n`);
        }
      }
    }
    
    return latestAliasId;
  }
  
  /**
   * Gets the ARN of the specified Agent Alias.
   * 
   * @param {string} agentId - Id of the agent
   * @param {string} agentAliasId - Id of the agent alias for which to get the ARN
   * @param {boolean} verbose - Whether to print verbose output
   * @returns {Promise<string>} ARN of the specified Agent Alias
   */
  async getAgentAliasArn(agentId, agentAliasId, verbose = false) {
    const getAliasParams = {
      agentId: agentId,
      agentAliasId: agentAliasId
    };
    
    const agentAlias = await this._bedrockAgentClient.send(
      new GetAgentAliasCommand(getAliasParams)
    );
    
    return agentAlias.agentAlias.agentAliasArn;
  }
  
  /**
   * Gets the Agent ID for the specified Agent.
   * 
   * @param {string} agentName - Name of the agent whose ID is to be returned
   * @returns {Promise<string|null>} Agent ID, or null if not found
   */
  async getAgentIdByName(agentName) {
    const listAgentsParams = {
      maxResults: 100
    };
    
    const getAgentsResp = await this._bedrockAgentClient.send(
      new ListAgentsCommand(listAgentsParams)
    );
    
    const agentsJson = getAgentsResp.agentSummaries;
    const targetAgent = agentsJson.find(agent => agent.agentName === agentName);
    
    return targetAgent ? targetAgent.agentId : null;
  }
  
  /**
   * Associates a Knowledge Base with an Agent, and prepares the agent.
   * 
   * @param {string} agentId - Id of the agent
   * @param {string} description - Description of the KB
   * @param {string} kbId - Id of the KB
   * @returns {Promise<void>}
   */
  async associateKbWithAgent(agentId, description, kbId) {
    await this.waitAgentStatusUpdate(agentId);
    
    const associateParams = {
      agentId: agentId,
      agentVersion: "DRAFT",
      description: description,
      knowledgeBaseId: kbId,
      knowledgeBaseState: "ENABLED"
    };
    
    await this._bedrockAgentClient.send(
      new AssociateAgentKnowledgeBaseCommand(associateParams)
    );
    
    const prepareParams = {
      agentId: agentId
    };
    
    await this._bedrockAgentClient.send(
      new PrepareAgentCommand(prepareParams)
    );
  }
  
  /**
   * Gets the Agent ARN for the specified Agent.
   * 
   * @param {string} agentName - Name of the agent whose ARN is to be returned
   * @returns {Promise<string>} Agent ARN
   * @throws {Error} If agent not found
   */
  async getAgentArnByName(agentName) {
    const agentId = await this.getAgentIdByName(agentName);
    
    if (!agentId) {
      throw new Error(`Agent ${agentName} not found`);
    }
    
    const getAgentParams = {
      agentId: agentId
    };
    
    const getAgentResp = await this._bedrockAgentClient.send(
      new GetAgentCommand(getAgentParams)
    );
    
    return getAgentResp.agent.agentArn;
  }
  
  /**
   * Gets the current Agent Instructions that are used by the specified Agent.
   * 
   * @param {string} agentName - Name of the agent whose Instructions are to be returned
   * @returns {Promise<string>} Agent instructions
   * @throws {Error} If agent not found
   */
  async getAgentInstructionsByName(agentName) {
    const agentId = await this.getAgentIdByName(agentName);
    
    if (!agentId) {
      throw new Error(`Agent ${agentName} not found`);
    }
    
    const getAgentParams = {
      agentId: agentId
    };
    
    const getAgentResp = await this._bedrockAgentClient.send(
      new GetAgentCommand(getAgentParams)
    );
    
    return getAgentResp.agent.instruction;
  }
  
  /**
   * Allows the specified Agent to invoke the specified Lambda function by adding the appropriate permission.
   * 
   * @param {string} agentId - Id of the agent
   * @param {string} lambdaFunctionName - Name of the Lambda function
   * @returns {Promise<void>}
   * @private
   */
  async _allowAgentLambda(agentId, lambdaFunctionName) {
    await this._ensureAccountId();
    
    const permissionParams = {
      FunctionName: lambdaFunctionName,
      StatementId: `allow_bedrock_${agentId}`,
      Action: "lambda:InvokeFunction",
      Principal: "bedrock.amazonaws.com",
      SourceArn: `arn:aws:bedrock:${this._region}:${this._accountId}:agent/${agentId}`
    };
    
    await this._lambdaClient.send(
      new AddPermissionCommand(permissionParams)
    );
  }
  
  /**
   * Makes a comma separated string of agent ids from a list of agent ARNs.
   * 
   * @param {Array<string>} agentArns - List of agent ARNs
   * @returns {string} Comma separated string of agent ids
   * @private
   */
  _makeAgentString(agentArns = null) {
    if (!agentArns) {
      return "";
    } else {
      return agentArns
        .map(agentArn => agentArn.split("/")[1])
        .join(",");
    }
  }
  
  /**
   * Creates a new Lambda function that implements a set of actions for an Agent Action Group.
   * 
   * @param {string} agentName - Name of the existing Agent that this Lambda will support
   * @param {string} lambdaFunctionName - Name of the Lambda function to create
   * @param {string} sourceCodeFile - Name of the file containing the Lambda source code
   * @param {Object} additionalFunctionIamPolicy - Additional IAM policy to attach to the Lambda function
   * @param {Array<string>} subAgentArns - List of ARNs of the sub-agents that this Lambda is allowed to invoke
   * @param {Array<string>} dynamoArgs - Arguments for DynamoDB table creation [tableName, pkField, skField]
   * @returns {Promise<string>} ARN of the new Lambda function
   */
