from logger import logger
from datetime import datetime, timedelta
import config
import utils
import graphql


def notify_change_status(issues):
    for issue in issues:
        if issue.get('state') == 'CLOSED':
            continue

        issue_content = issue.get('content', {})
        if not issue_content:
            logger.warning(f'Issue object does not contain "content": {issue}')
            continue

        issueId = issue_content.get('id')
      
        project_items = issue.get('projectItems', {}).get('nodes', [])
        if not project_items:
            logger.warning(f'No project items found for issue {issueId}')
            continue

        project_item = project_items[0]
        if not project_item.get('fieldValueByName'):
            logger.warning(f'Project item does not contain "fieldValueByName": {project_item}')
            continue

        current_status = project_item['fieldValueByName'].get('name')
        if not current_status:
            logger.warning(f'No status found in fieldValueByName for project item: {project_item}')
            continue

        if current_status == 'QA Testing':
            comment_text_qatesting = "Testing will be available in 15 minutes."

            if not utils.check_comment_exists_for_qatesting(issueId, comment_text_qatesting):
                comment = utils.prepare_qatesting_issue_comment(
                    issue=issue_content,
                    assignees=issue_content.get('assignees', {}).get('nodes', []),
                )

                if not config.dry_run:
                    comment_result = graphql.add_issue_comment(issueId, comment)
                    if comment_result:
                        logger.info(f'Comment added to issue #{issue_content.get("number")} ({issueId})')
                    else:
                        logger.error(f'Failed to add comment to issue #{issue_content.get("number")} ({issueId})')
            else:
                logger.info(f'Comment already exists for issue #{issue_content.get("number")} ({issueId})')



def notify_due_date_changes(issues):
    for projectItem in issues:
        # Safely extract 'content' from projectItem
        issue = projectItem.get('content')
        if not issue:
            logger.error(f"Missing 'content' in project item: {projectItem}")
            continue

        # Get the list of assignees
        assignees = issue.get('assignees', {}).get('nodes', [])
        
        # Get the due date value
        due_date = None
        due_date_obj = None
        try:
            due_date = projectItem.get('dueDate').get('date')
            if due_date:
                due_date_obj = datetime.strptime(due_date, "%Y-%m-%d").date()
        except (AttributeError, ValueError) as e:
            continue  # Skip this issue and move to the next

        issue_title = issue.get('title', 'Unknown Title')
        issueId = issue.get('id', 'Unknown ID')

        if not due_date_obj:
            logger.info(f'No due date found for issue {issue_title}')
            continue
        
        expected_comment = f"The Due Date is updated to: {due_date_obj.strftime('%b %d, %Y')}."
      
        # Check if the comment already exists
        if not utils.check_comment_exists(issueId, expected_comment):
            # Prepare the notification content
                
            comment = utils.prepare_duedate_comment(
                issue=issue,
                assignees=assignees, 
                due_date=due_date_obj
            )
                
            if not config.dry_run:
                try:
                    # Add the comment to the issue
                    graphql.add_issue_comment(issueId, comment)
                    logger.info(f'Comment added to issue with title {issue_title}. Due date is {due_date_obj}.')
                except Exception as e:
                    logger.error(f"Failed to add comment to issue {issue_title} (ID: {issueId}): {e}")
            else:
                logger.info(f'DRY RUN: Comment prepared for issue with title {issue_title}. Due date is {due_date_obj}.')


def fields_based_on_due_date(project, issue, updates):
    # Extract all field nodes from the project
    field_nodes = project["fields"]["nodes"]

    # Identify the 'Release' and 'Week' fields by name
    release_field = next((field for field in field_nodes if field and field["name"] == "Release"), None)
    week_field = next((field for field in field_nodes if field and field["name"] == "Week"), None)

    # Get the options for 'Release' and 'Week' fields
    release_options = release_field['options']
    week_options = week_field['configuration']['iterations'] + week_field['configuration']['completedIterations']

    comment_fields = []

    # Skip processing if the issue does not have a due date
    if not issue.get('dueDate'):
        return comment_fields

    # Retrieve the due date from the issue
    due_date = issue.get('dueDate').get('date')
    output = due_date

    # Handle missing 'week' field by finding the appropriate week based on the due date
    week = utils.find_week(weeks=week_options, date_str=due_date)
    if week and week != issue.get('week'):
        # Add the 'week' field update to the updates list
        updates.append({
            "field_id": week_field['id'],
            "type": "iteration",
            "value": week['id']
        })
        output += f' -> Week {week}'
        comment_fields.append({'field': 'Week', 'value': week['title']})

    # Handle missing 'release' field by finding the appropriate release based on the due date
    release = utils.find_release(releases=release_options, date_str=due_date)
    if release and release != issue.get('release'):
        # Add the 'release' field update to the updates list
        updates.append({
            "field_id": release_field['id'],
            "type": "single_select",
            "value": release['id']
        })
        output += f' -> Release {release}'
        comment_fields.append({'field': 'Release', 'value': release['name']})

    # Log the updates for debugging or tracking purposes
    logger.debug(output)

    return comment_fields


def fields_based_on_estimation(project, issue, updates):
    # Extract all field nodes from the project
    field_nodes = project["fields"]["nodes"]

    # Identify the 'Size' field by name
    size_field = next((field for field in field_nodes if field and field["name"] == "Size"), None)
    size_options = size_field['options']

    comment_fields = []

    # Skip processing if the issue does not have an estimate
    if not issue.get('estimate'):
        return comment_fields

    # Retrieve the estimate value from the issue
    estimate = issue.get('estimate').get('name')
    output = estimate

    # Find the size corresponding to the estimate and update if found
    size = utils.find_size(sizes=size_options, estimate_name=estimate)
    if size and size != issue.get('size'):
        # Add the 'size' field update to the updates list
        updates.append({
            "field_id": size_field['id'],
            "type": "single_select",
            "value": size['id']
        })
        # Log the update for debugging or tracking purposes
        logger.debug(f'{output} -> Size {size}')
        comment_fields.append({'field': 'Size', 'value': size['name']})

    return comment_fields


def update_fields(issues):
    # Fetch the project details from GraphQL
    project = graphql.get_project(
        organization_name=config.repository_owner,
        project_number=config.project_number
    )

    comments_issue = None
    if config.comments_issue_repo:
        comments_issue = graphql.get_issue(
            owner_name=config.repository_owner,
            repo_name=config.comments_issue_repo,
            issue_number=config.comments_issue_number
        )
    

    # Iterate over all issues to check and set missing fields
    for issue in issues:
        updates = []
        # Determine missing fields based on estimation and due date
        comment_fields = fields_based_on_estimation(project, issue, updates)
        comment_fields += fields_based_on_due_date(project, issue, updates)

        # Apply updates if not in dry run mode
        if updates:
            # Constructing the comment
            comment = "The following fields have been updated:\n" + "\n".join(
                [f"- {item['field']}: **{item['value']}**" for item in comment_fields]
            )

            if not config.dry_run:
                graphql.update_project_item_fields(
                    project_id=project['id'],
                    item_id=issue['id'],
                    updates=updates
                )

                # Add a comment summarizing the updated fields
                if comments_issue:
                    comment = f"Issue {issue['content']['url']}: {comment}"
                    graphql.add_issue_comment(comments_issue['id'], comment)
                else:
                    graphql.add_issue_comment(issue['content']['id'], comment)

            # Log the output
            logger.info(f"Comment has been added to: {issue['content']['url']} with comment {comment}")


def main():
    # Log the start of the process
    logger.info('Process started...')
    if config.dry_run:
        logger.info('DRY RUN MODE ON!')

    # Fetch all open issues from the project
    issues = graphql.get_project_issues(
        owner=config.repository_owner,
        owner_type=config.repository_owner_type,
        project_number=config.project_number,
        filters={'open_only': True}
    )

    # Exit if no issues are found
    if not issues:
        logger.info('No issues have been found')
        return

    # Process the issues to update fields
    update_fields(issues)

    # Process to identify change in the due date and write a comment in the issue
    notify_due_date_changes(issues)
    notify_change_status(issues)

    logger.info('Process finished...')


if __name__ == "__main__":
    main()
