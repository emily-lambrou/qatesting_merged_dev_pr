import requests
import config
from logger import logger


def get_project(organization_name, project_number):
    # GraphQL query
    query = """
    query($organization: String!, $projectNumber: Int!) {
        organization(login: $organization) {
            projectV2(number: $projectNumber) {
              id
              fields(first: 100) {
                nodes {
                  ... on ProjectV2SingleSelectField {
                    id
                    name
                    options {
                        id
                        name
                    }
                  }
                  ... on ProjectV2IterationField {
                    id
                    name
                    configuration {
                        iterations {
                            id
                            title
                            startDate
                            duration
                        }
                        completedIterations {
                            id
                            title
                            startDate
                            duration
                        }
                    }
                  }
                }
              }
            }
        }
    }
    """

    variables = {
        'organization': organization_name,
        'projectNumber': project_number
    }
    response = requests.post(
        config.api_endpoint,
        json={"query": query, "variables": variables},
        headers={"Authorization": f"Bearer {config.gh_token}"}
    )

    return response.json().get('data').get('organization').get('projectV2')


def get_project_issues(owner, owner_type, project_number, filters=None, after=None, issues=None):
    query = f"""
    query GetProjectIssues($owner: String!, $projectNumber: Int!, $after: String)  {{
          {owner_type}(login: $owner) {{
            projectV2(number: $projectNumber) {{
              id
              title
              number
              items(first: 100,after: $after) {{
                nodes {{
                  id
                  dueDate: fieldValueByName(name: "Due Date") {{
                    ... on ProjectV2ItemFieldDateValue {{
                      id
                      date
                    }}
                  }}
                  release: fieldValueByName(name: "Release") {{
                    ... on ProjectV2ItemFieldSingleSelectValue {{
                      id: optionId
                      name
                    }}
                  }}
                  week: fieldValueByName(name: "Week") {{
                    ... on ProjectV2ItemFieldIterationValue {{
                      id: iterationId
                      title
                      startDate
                      duration
                    }}
                  }}
                  estimate: fieldValueByName(name: "Estimate") {{
                    ... on ProjectV2ItemFieldSingleSelectValue {{
                      name
                      id
                    }}
                  }}
                  size: fieldValueByName(name: "Size") {{
                    ... on ProjectV2ItemFieldSingleSelectValue {{
                      id: optionId
                      name
                    }}
                  }}
                  content {{
                    ... on Issue {{
                      id
                      title
                      number
                      state
                      url
                      assignees(first:20) {{
                        nodes {{
                          name
                          email
                          login
                        }}
                      }}
                    }}
                  }}
                }}
                pageInfo {{
                endCursor
                hasNextPage
                hasPreviousPage
              }}
              totalCount
              }}
            }}
          }}
        }}
    """

    variables = {
        'owner': owner,
        'projectNumber': project_number,
        'after': after
    }

    response = requests.post(
        config.api_endpoint,
        json={"query": query, "variables": variables},
        headers={"Authorization": f"Bearer {config.gh_token}"}
    )

    if response.json().get('errors'):
        logger.info(response.json().get('errors'))

    if issues is None:
        issues = []

    nodes = response.json().get('data').get(owner_type).get('projectV2').get('items').get('nodes')

    if filters:
        filtered_issues = []
        for node in nodes:
            if filters.get('open_only') and node['content'].get('state') != 'OPEN':
                continue

            filtered_issues.append(node)

        nodes = filtered_issues

    issues = issues + nodes

    pageinfo = response.json().get('data').get(owner_type).get('projectV2').get('items').get('pageInfo')
    if pageinfo.get('hasNextPage'):
        return get_project_issues(
            owner=owner,
            owner_type=owner_type,
            project_number=project_number,
            after=pageinfo.get('endCursor'),
            filters=filters,
            issues=issues,
        )

    return issues


def get_status_project_issues(owner, owner_type, project_number, status_field_name, filters=None, after=None, issues=None):
    query = f"""
    query GetProjectIssues($owner: String!, $projectNumber: Int!, $status: String!, $after: String) {{
        {owner_type}(login: $owner) {{
            projectV2(number: $projectNumber) {{
                id
                title
                number
                items(first: 100, after: $after) {{
                    nodes {{
                        id
                        fieldValueByName(name: $status) {{
                            ... on ProjectV2ItemFieldSingleSelectValue {{
                                id
                                name
                            }}
                        }}
                        content {{
                            ... on Issue {{
                                id
                                title
                                number
                                state
                                url
                                assignees(first: 20) {{
                                    nodes {{
                                        name
                                        email
                                        login
                                    }}
                                }}
                            }}
                        }}
                    }}
                    pageInfo {{
                        endCursor
                        hasNextPage
                        hasPreviousPage
                    }}
                    totalCount
                }}
            }}
        }}
    }}
    """

    variables = {
        'owner': owner,
        'projectNumber': project_number,
        'status': status_field_name,
        'after': after
    }

    try:
        response = requests.post(
            config.api_endpoint,
            json={"query": query, "variables": variables},
            headers={"Authorization": f"Bearer {config.gh_token}"}
        )
    
        data = response.json()
    
        if 'errors' in data:
            logging.error(f"GraphQL query errors: {data['errors']}")
            return []
          
        owner_data = data.get('data', {}).get(owner_type, {})
        project_data = owner_data.get('projectV2', {})
        items_data = project_data.get('items', {})
        pageinfo = items_data.get('pageInfo', {})
        nodes = items_data.get('nodes', [])
    
        if issues is None:
            issues = []
    
        if filters:
            filtered_issues = []
            for node in nodes:
                issue_content = node.get('content', {})
                if not issue_content:
                    continue
    
                issue_id = issue_content.get('id')
                if not issue_id:
                    continue

                field_value = node.get('fieldValueByName')
                current_status = field_value.get('name') if field_value else None
       
                if filters.get('open_only') and issue_content.get('state') != 'OPEN':
                    logging.debug(f"Filtering out issue ID {issue_id} with state {issue_content.get('state')}")
                    continue
       
                if current_status == 'QA Testing':
                    if not utils.check_comment_exists(issue_id, "Testing will be available in 15 minutes."):
                        logging.debug(f"Adding issue ID {issue_id} as status is 'QA Testing'")
                        add_issue_comment(issue_id, "Testing will be available in 15 minutes.")
                        logging.info(f"Comment added to issue {issue_id}")
                        filtered_issues.append(node)
                    else:
                        logging.info(f"Comment already exists for issue {issue_id}")

            nodes = filtered_issues
    
        issues = issues + nodes
    
        if pageinfo.get('hasNextPage'):
            return get_project_issues(
                owner=owner,
                owner_type=owner_type,
                project_number=project_number,
                after=pageinfo.get('endCursor'),
                filters=filters,
                issues=issues,
                status_field_name=status_field_name
            )
    
        return issues
    except requests.RequestException as e:
        logging.error(f"Request error: {e}")
        return []









def get_issue(owner_name, repo_name, issue_number):
    # GraphQL query
    query = """
    query($owner: String!, $repo: String!, $issueNumber: Int!) {
        repository(owner: $owner, name: $repo) {
            issue(number: $issueNumber) {
                id
                number
                title
                body
                state
                author {
                    login
                }
                createdAt
                updatedAt
                labels(first: 10) {
                    nodes {
                        name
                        color
                    }
                }
            }
        }
    }
    """

    variables = {
        'owner': owner_name,
        'repo': repo_name,
        'issueNumber': issue_number
    }

    response = requests.post(
        config.api_endpoint,
        json={"query": query, "variables": variables},
        headers={"Authorization": f"Bearer {config.gh_token}"}
    )

    # Parse and return the issue details
    data = response.json()
    return data.get('data', {}).get('repository', {}).get('issue', None)


def add_issue_comment(issueId, comment):
    mutation = """
    mutation AddIssueComment($issueId: ID!, $comment: String!) {
        addComment(input: {subjectId: $issueId, body: $comment}) {
            clientMutationId
        }
    }
    """

    variables = {
        'issueId': issueId,
        'comment': comment
    }
    response = requests.post(
        config.api_endpoint,
        json={"query": mutation, "variables": variables},
        headers={"Authorization": f"Bearer {config.gh_token}"}
    )
    if response.json().get('errors'):
        logger.info(response.json().get('errors'))

    return response.json().get('data')



def get_issue_comments(issueId):
    query = """
    query GetIssueComments($issueId: ID!, $afterCursor: String) {
        node(id: $issueId) {
            ... on Issue {
                comments(first: 100, after: $afterCursor) {
                    nodes {
                        body
                        createdAt
                        author {
                            login
                        }
                    }
                    pageInfo {
                        endCursor
                        hasNextPage
                    }
                }
            }
        }
    }
    """

    variables = {
        'issueId': issueId,
        'afterCursor': None
    }

    all_comments = []

    try:
        while True:
            response = requests.post(
                config.api_endpoint,
                json={"query": query, "variables": variables},
                headers={"Authorization": f"Bearer {config.gh_token}"}
            )

            data = response.json()

            if 'errors' in data:
                logging.error(f"GraphQL query errors: {data['errors']}")
                break

            comments_data = data.get('data', {}).get('node', {}).get('comments', {})
            comments = comments_data.get('nodes', [])
            all_comments.extend(comments)

            pageinfo = comments_data.get('pageInfo', {})
            if not pageinfo.get('hasNextPage'):
                break

            # Set the cursor for the next page
            variables['afterCursor'] = pageinfo.get('endCursor')

        return all_comments

    except requests.RequestException as e:
        logging.error(f"Request error: {e}")
        return []

def update_project_item_fields(project_id, item_id, updates):
    """
    Updates multiple fields for a project item.

    :param project_id: The ID of the project.
    :param item_id: The ID of the item to update.
    :param updates: A list of updates, where each update is a dictionary with:
                    - field_id: ID of the field to update
                    - type: Type of the field ('single_select' or 'iteration')
                    - value: The new value (singleSelectOptionId for single_select, iterationId for iteration)
    """
    mutation = """
    mutation UpdateProjectV2ItemFieldValue($input: UpdateProjectV2ItemFieldValueInput!) {
      updateProjectV2ItemFieldValue(input: $input) {
        projectV2Item {
          id
        }
      }
    }
    """

    headers = {
        "Authorization": f"Bearer {config.gh_token}",  # Replace with your GitHub token
        "Content-Type": "application/json"
    }

    for update in updates:
        input_value = {
            "projectId": project_id,
            "itemId": item_id,
            "fieldId": update["field_id"],
            "value": {}
        }

        if update["type"] == "single_select":
            input_value["value"]["singleSelectOptionId"] = update["value"]
        elif update["type"] == "iteration":
            input_value["value"]["iterationId"] = update["value"]
        else:
            logger.info(f"Unsupported field type: {update['type']}")
            continue

        variables = {"input": input_value}

        response = requests.post(
            config.api_endpoint,
            json={"query": mutation, "variables": variables},
            headers=headers
        )

        if response.status_code == 200:
            response_data = response.json()
            if response_data.get("errors"):
                logger.info("Errors:", response_data["errors"])
        else:
            logger.info(f"HTTP error {response.status_code}: {response.text}")
