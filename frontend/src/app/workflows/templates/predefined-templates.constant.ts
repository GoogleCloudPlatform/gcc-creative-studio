/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import {NodeTypes, StepStatusEnum, WorkflowTemplate} from '../workflow.models';

export const PREDEFINED_WORKFLOW_TEMPLATES: WorkflowTemplate[] = [
  {
    id: 'tmpl-29940221-6bae-41c1-9aee-1ec688313337',
    name: 'Fashion Stylist',
    description: 'Create a weather specific outfit for a specific occasion',
    isPredefined: true,
    steps: [
      {
        stepId: 'user_input',
        status: StepStatusEnum.IDLE,
        outputs: {
          City: {
            type: 'text',
          },
          Gender: {
            type: 'text',
          },
          Occasion: {
            type: 'text',
          },
          Style_Details: {
            type: 'text',
          },
        },
        inputs: {},
        settings: {
          definitions: [
            {
              id: 'def_city',
              name: 'City',
              type: 'text',
            },
            {
              id: 'def_gender',
              name: 'Gender',
              type: 'text',
            },
            {
              id: 'def_occasion',
              name: 'Occasion',
              type: 'text',
            },
            {
              id: 'def_style_details',
              name: 'Style Details',
              type: 'text',
            },
          ],
        },
        type: NodeTypes.USER_INPUT,
      },
      {
        stepId: 'weather_forecast_step',
        status: StepStatusEnum.IDLE,
        outputs: {
          generated_text: {
            type: 'text',
          },
        },
        inputs: {
          prompt:
            'Use the information you get from <city> to get and return weather conditions',
          input_images: null,
          input_videos: null,
          city: {
            step: 'user_input',
            output: 'City',
            _definitionId: 'def_city',
          },
        },
        settings: {
          model: 'gemini-3.8-flash',
          temperature: 0.7,
        },
        type: NodeTypes.GENERATE_TEXT,
      },
      {
        stepId: 'wardrobe_consultant_step',
        status: StepStatusEnum.IDLE,
        outputs: {
          generated_text: {
            type: 'text',
          },
        },
        inputs: {
          prompt:
            'You\'re a knowledgeable, enthusiastic, and supportive personal wardrobe consultant. You know all the styles, trends and other details appropriate for people of all ages, identities and styles. \nYour goal is to create one outfit that fits the following information. \nWeather conditions: <weather>\nWardrobe requirements: model is a <gender> occasion: <occasion>, more details are <details>.\nYou must make sure the outfit is appropriate for the weather. For example, you should not recommend a t-shirt as the only top if it\'s 55 degrees F.\nThe outfit should give the title and description as shown below, nothing else:\na brief phrase that identifies this outfit; make it like a memorable one-liner if possible\na short description of the clothing and accessory items that are important for the outfit accompanied by what role they play in making this outfit work for you and your occasion.\n\ngold rule: start you output with "Create an image based on this description below. Be sure to depict the person close up way, being able to see, head to toe, the entire outfit. Any personal details like age, gender race, etc should be reflected in the image: "',
          input_images: null,
          input_videos: null,
          gender: {
            step: 'user_input',
            output: 'Gender',
            _definitionId: 'def_gender',
          },
          details: {
            step: 'user_input',
            output: 'Style_Details',
            _definitionId: 'def_style_details',
          },
          weather: {
            step: 'weather_forecast_step',
            output: 'generated_text',
          },
          occasion: {
            step: 'user_input',
            output: 'Occasion',
            _definitionId: 'def_occasion',
          },
        },
        settings: {
          model: 'gemini-3.8-flash',
          temperature: 0.7,
        },
        type: NodeTypes.GENERATE_TEXT,
      },
      {
        stepId: 'outfit_image_step',
        status: StepStatusEnum.IDLE,
        outputs: {
          generated_image: {
            type: 'image',
          },
        },
        inputs: {
          prompt: {
            step: 'wardrobe_consultant_step',
            output: 'generated_text',
          },
          input_images: null,
          input_image: null,
          model_image: null,
          top_image: null,
          bottom_image: null,
          dress_image: null,
          shoes_image: null,
        },
        settings: {
          mode: 'generate_image',
          model: 'gemini-3.1-flash-image',
          aspect_ratio: '1:1',
          brand_guidelines: false,
          resolution: '1K',
          upscale_factor: 'x2',
          enhance_input_image: false,
          image_preservation_factor: null,
        },
        type: NodeTypes.IMAGE,
      },
    ],
    positions: {
      user_input: {x: 80, y: 120},
      weather_forecast_step: {x: 480, y: 120},
      wardrobe_consultant_step: {x: 880, y: 120},
      outfit_image_step: {x: 1280, y: 120},
    },
  },
  {
    id: 'tmpl-e9e5ab08-d4e4-4a66-ad76-ce0323dfe91f',
    name: 'Social Media Post',
    description:
      'Generate an engaging social media caption and promotional image for a business',
    isPredefined: true,
    steps: [
      {
        stepId: 'user_input',
        status: StepStatusEnum.IDLE,
        outputs: {
          Business_name: {
            type: 'text',
          },
          Purpose_of_the_post: {
            type: 'text',
          },
        },
        inputs: {},
        settings: {
          definitions: [
            {
              id: 'def_business_name',
              name: 'Business name',
              type: 'text',
            },
            {
              id: 'def_purpose_of_post',
              name: 'Purpose of the post',
              type: 'text',
            },
          ],
        },
        type: NodeTypes.USER_INPUT,
      },
      {
        stepId: 'company_research_step',
        status: StepStatusEnum.IDLE,
        outputs: {
          generated_text: {
            type: 'text',
          },
        },
        inputs: {
          prompt:
            'Act as the social media producer.\n\nSearch from internet about the company <business> and its products, services, and community involvement. Gather relevant information to create an engaging social media caption.',
          input_images: null,
          input_videos: null,
          business: {
            step: 'user_input',
            output: 'Business_name',
            _definitionId: 'def_business_name',
          },
        },
        settings: {
          model: 'gemini-3.8-flash',
          temperature: 0.7,
        },
        type: NodeTypes.GENERATE_TEXT,
      },
      {
        stepId: 'caption_generator_step',
        status: StepStatusEnum.IDLE,
        outputs: {
          generated_text: {
            type: 'text',
          },
        },
        inputs: {
          prompt:
            'Act as the social media producer.\ncreate a social media caption. The caption uses up to 3 hashtags based on the reported info. Make sure you include purpose of the post <purpose> and references to the company name <business>, its products, the city or community of applicable and other identifying information to make it feel genuine, the information from company is: <businness_desc>',
          input_images: null,
          input_videos: null,
          purpose: {
            step: 'user_input',
            output: 'Purpose_of_the_post',
            _definitionId: 'def_purpose_of_post',
          },
          business: {
            step: 'user_input',
            output: 'Business_name',
            _definitionId: 'def_business_name',
          },
          businness_desc: {
            step: 'company_research_step',
            output: 'generated_text',
          },
        },
        settings: {
          model: 'gemini-3.8-flash',
          temperature: 0.7,
        },
        type: NodeTypes.GENERATE_TEXT,
      },
      {
        stepId: 'image_prompt_generator_step',
        status: StepStatusEnum.IDLE,
        outputs: {
          generated_text: {
            type: 'text',
          },
        },
        inputs: {
          prompt:
            'Generate a prompt based on this text:\n\n"Act as the social media producer.\n\nCreate an image using this technique:\n- Come up with a short, 2-3 word catchy phrase that expresses the essence of the social media caption: <caption>.\n- Generate a new image that would go well with the social media caption. Make sure to have no text in this generated image.\n- Using image generation edit, add the catchy phrase over the top of the provided or generated image in white fancy script.\n- In the same style as the text, also add what look to be hand drawn stars, etc. Choose the type of shape that makes most sense for this caption and style. Draw on Only 6-8 of these.\n\nThe text and the stars should give the result a fun, informal feel."',
          input_images: null,
          input_videos: null,
          caption: {
            step: 'caption_generator_step',
            output: 'generated_text',
          },
        },
        settings: {
          model: 'gemini-3.8-flash',
          temperature: 0.7,
        },
        type: NodeTypes.GENERATE_TEXT,
      },
      {
        stepId: 'post_image_step',
        status: StepStatusEnum.IDLE,
        outputs: {
          generated_image: {
            type: 'image',
          },
        },
        inputs: {
          prompt: {
            step: 'image_prompt_generator_step',
            output: 'generated_text',
          },
          input_images: null,
          input_image: null,
          model_image: null,
          top_image: null,
          bottom_image: null,
          dress_image: null,
          shoes_image: null,
        },
        settings: {
          mode: 'generate_image',
          model: 'gemini-3.1-flash-image',
          aspect_ratio: '1:1',
          brand_guidelines: false,
          resolution: '1K',
          upscale_factor: 'x2',
          enhance_input_image: false,
          image_preservation_factor: null,
        },
        type: NodeTypes.IMAGE,
      },
    ],
    positions: {
      user_input: {x: 80, y: 120},
      company_research_step: {x: 480, y: 120},
      caption_generator_step: {x: 880, y: 120},
      image_prompt_generator_step: {x: 1280, y: 120},
      post_image_step: {x: 1680, y: 120},
    },
  },
  {
    id: 'tmpl-2b08aefe-96e1-4333-92d4-69c28607b411',
    name: 'Product Video Ad',
    description:
      'Research a product, craft ad copy and video script, and generate a video ad',
    isPredefined: true,
    steps: [
      {
        stepId: 'user_input',
        status: StepStatusEnum.IDLE,
        outputs: {
          Product_name: {
            type: 'text',
          },
          Target_audience: {
            type: 'text',
          },
        },
        inputs: {},
        settings: {
          definitions: [
            {
              id: 'def_product_name',
              name: 'Product name',
              type: 'text',
            },
            {
              id: 'def_target_audience',
              name: 'Target audience',
              type: 'text',
            },
          ],
        },
        type: NodeTypes.USER_INPUT,
      },
      {
        stepId: 'product_research_step',
        status: StepStatusEnum.IDLE,
        outputs: {
          generated_text: {
            type: 'text',
          },
        },
        inputs: {
          prompt:
            "Use internet to perform: Research the product's specifications and value proposition using web search for this product: <product>",
          input_images: null,
          input_videos: null,
          product: {
            step: 'user_input',
            output: 'Product_name',
            _definitionId: 'def_product_name',
          },
        },
        settings: {
          model: 'gemini-3.8-flash',
          temperature: 0.7,
        },
        type: NodeTypes.GENERATE_TEXT,
      },
      {
        stepId: 'ad_copywriter_step',
        status: StepStatusEnum.IDLE,
        outputs: {
          generated_text: {
            type: 'text',
          },
        },
        inputs: {
          prompt:
            'You are an expert ad copywriter, skilled at crafting compelling two-line ad text that captures attention and drives engagement. Your task is to generate ad text for a given product, targeting a specific audience, based on research about the product\'s specifications and value proposition. The ad text should be concise, attention-grabbing, and highlight the key benefits of the product for the target audience, and should be exactly two lines long.\n\n# Step by Step instructions\n1.  Note the given Product Name, Target Audience, and Product Research.\n2.  Write the first line of ad text, referencing the Product Name, Target Audience, and Product Research.\n3.  Write the second line of ad text, referencing the Product Name, Target Audience, and Product Research.\n4.  Check that the ad text is exactly two lines long, attention-grabbing, and highlights the key benefits of the product for the target audience. If not, go back to step 2 and rewrite the ad text.\n\nProduct Name: <product>\nTarget Audience: <target>\nProduct Research: <research>\nIMPORTANT NOTE: Start directly with the output, do not output any delimiters and You are working as part of an AI system, so no chit-chat and no explaining what you\'re doing and why. DO NOT start with "Okay", or "Alright" or any preambles. Just the output, please.',
          input_images: null,
          input_videos: null,
          target: {
            step: 'user_input',
            output: 'Target_audience',
            _definitionId: 'def_target_audience',
          },
          product: {
            step: 'user_input',
            output: 'Product_name',
            _definitionId: 'def_product_name',
          },
          research: {
            step: 'product_research_step',
            output: 'generated_text',
          },
        },
        settings: {
          model: 'gemini-3.8-flash',
          temperature: 0.7,
        },
        type: NodeTypes.GENERATE_TEXT,
      },
      {
        stepId: 'video_script_step',
        status: StepStatusEnum.IDLE,
        outputs: {
          generated_text: {
            type: 'text',
          },
        },
        inputs: {
          prompt:
            'You are a creative video script writer, adept at crafting compelling visual narratives for short-form video. Your task is to generate a detailed description of a video clip that will showcase a product to a specific target audience. The video clip will be less than 10 seconds long and contain no audio, so your description must capture the essence of the scene, focusing on visual elements that convey awe and excitement. The description should provide clear guidance for a video generation API, ensuring that the generated video aligns with the product\'s value proposition and resonates with the target audience.\n\n# Step by Step instructions\n1.  Note the Product Name, Target Audience, and Product Research provided.\n2.  Craft an initial sentence for the video description, focusing on the product in use by a member of the Target Audience. Highlight a key visual element that demonstrates a core value proposition from the Product Research.\n3.  Add a second sentence detailing the user\'s reaction, ensuring it visually conveys "awe and excitement" without relying on audio cues. Consider elements like facial expressions, body language, and visual effects.\n4.  Review the description. Does it accurately and vividly describe a short video (under 10 seconds) showcasing the product to the target audience with awe and excitement? If not, revise steps 2 and 3 to improve clarity, detail, and visual impact.\n\nProduct Name:<product>\nTarget Audience:<target>\nProduct Research:<research>\nIMPORTANT NOTE: Start directly with the output, do not output any delimiters. You are working as part of an AI system, so no chit-chat and no explaining what you\'re doing and why.\nDO NOT start with "Okay", or "Alright" or any preambles. Just the output, please.\n',
          input_images: null,
          input_videos: null,
          target: {
            step: 'user_input',
            output: 'Target_audience',
            _definitionId: 'def_target_audience',
          },
          product: {
            step: 'user_input',
            output: 'Product_name',
            _definitionId: 'def_product_name',
          },
          research: {
            step: 'product_research_step',
            output: 'generated_text',
          },
        },
        settings: {
          model: 'gemini-3.8-flash',
          temperature: 0.7,
        },
        type: NodeTypes.GENERATE_TEXT,
      },
      {
        stepId: 'product_video_step',
        status: StepStatusEnum.IDLE,
        outputs: {
          generated_video: {
            type: 'video',
          },
        },
        inputs: {
          prompt: {
            step: 'video_script_step',
            output: 'generated_text',
          },
          input_images: null,
          input_video: null,
          input_audio: null,
          start_frame: null,
          end_frame: null,
        },
        settings: {
          model: 'gemini-omni-1.1-flash-preview',
          brand_guidelines: false,
          aspect_ratio: '16:9',
          duration_seconds: 4,
          input_mode: 'Text to Video',
          resolution: '1K',
        },
        type: NodeTypes.GENERATE_VIDEO,
      },
    ],
    positions: {
      user_input: {x: 80, y: 120},
      product_research_step: {x: 480, y: 120},
      ad_copywriter_step: {x: 880, y: 120},
      video_script_step: {x: 1280, y: 120},
      product_video_step: {x: 1680, y: 120},
    },
  },
];
