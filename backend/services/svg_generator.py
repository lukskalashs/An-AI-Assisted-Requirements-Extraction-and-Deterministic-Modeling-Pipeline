from xml.etree.ElementTree import Element, SubElement, tostring
from heapq import heappop, heappush
from itertools import count
from math import inf

from sqlalchemy.orm import Session

from services.diagram_layout import (
    _classes_for_diagram,
    _diagram_layout,
    _expand_erd_junctions,
    _relationships_for_diagram,
)


def _segment_clear(start, end, obstacles):
    x1, y1 = start
    x2, y2 = end
    for left, top, right, bottom in obstacles:
        if y1 == y2 and top < y1 < bottom and max(min(x1, x2), left) < min(max(x1, x2), right):
            return False
        if x1 == x2 and left < x1 < right and max(min(y1, y2), top) < min(max(y1, y2), bottom):
            return False
    return True


def _route_relationship(source_id, target_id, positions, previous_routes):
    source_x, source_y, source_width, source_height = positions[source_id]
    target_x, target_y, target_width, target_height = positions[target_id]
    source_rect = (source_x, source_y, source_x + source_width, source_y + source_height)
    target_rect = (target_x, target_y, target_x + target_width, target_y + target_height)
    padding = 22
    obstacles = [
        (x - padding, y - padding, x + width + padding, y + height + padding)
        for class_id, (x, y, width, height) in positions.items()
        if class_id not in {source_id, target_id}
    ]
    source_padded = (source_rect[0] - padding, source_rect[1] - padding, source_rect[2] + padding, source_rect[3] + padding)
    target_padded = (target_rect[0] - padding, target_rect[1] - padding, target_rect[2] + padding, target_rect[3] + padding)
    all_obstacles = obstacles + [source_padded, target_padded]
    source_ports = [
        ((source_rect[2], source_y + source_height // 2), (source_padded[2], source_y + source_height // 2)),
        ((source_rect[0], source_y + source_height // 2), (source_padded[0], source_y + source_height // 2)),
        ((source_x + source_width // 2, source_rect[3]), (source_x + source_width // 2, source_padded[3])),
        ((source_x + source_width // 2, source_rect[1]), (source_x + source_width // 2, source_padded[1])),
    ]
    target_ports = [
        ((target_rect[0], target_y + target_height // 2), (target_padded[0], target_y + target_height // 2)),
        ((target_rect[2], target_y + target_height // 2), (target_padded[2], target_y + target_height // 2)),
        ((target_x + target_width // 2, target_rect[1]), (target_x + target_width // 2, target_padded[1])),
        ((target_x + target_width // 2, target_rect[3]), (target_x + target_width // 2, target_padded[3])),
    ]

    xs = {point[0] for _, point in source_ports + target_ports}
    ys = {point[1] for _, point in source_ports + target_ports}
    for left, top, right, bottom in all_obstacles:
        xs.update((left, right))
        ys.update((top, bottom))
    xs = sorted(xs)
    ys = sorted(ys)
    x_index = {value: index for index, value in enumerate(xs)}
    y_index = {value: index for index, value in enumerate(ys)}
    blocked = {
        (ix, iy)
        for ix, x in enumerate(xs)
        for iy, y in enumerate(ys)
        if any(left < x < right and top < y < bottom for left, top, right, bottom in all_obstacles)
    }
    prior_segments = [
        (start, end)
        for route in previous_routes
        for start, end in zip(route, route[1:])
    ]

    def find_path(start_point, end_point):
        start = (x_index[start_point[0]], y_index[start_point[1]])
        goal = (x_index[end_point[0]], y_index[end_point[1]])
        serial = count()
        queue = [(0, next(serial), start[0], start[1], 0)]
        distances = {(start[0], start[1], 0): 0}
        previous = {}
        final_state = None
        while queue:
            cost, _, ix, iy, direction = heappop(queue)
            state = (ix, iy, direction)
            if cost != distances.get(state):
                continue
            if (ix, iy) == goal:
                final_state = state
                break
            for next_direction, (dx, dy) in enumerate(((1, 0), (-1, 0), (0, 1), (0, -1)), start=1):
                nx, ny = ix + dx, iy + dy
                if not (0 <= nx < len(xs) and 0 <= ny < len(ys)) or (nx, ny) in blocked:
                    continue
                current_point, next_point = (xs[ix], ys[iy]), (xs[nx], ys[ny])
                if not _segment_clear(current_point, next_point, all_obstacles):
                    continue
                length = abs(next_point[0] - current_point[0]) + abs(next_point[1] - current_point[1])
                overlap_penalty = sum(
                    1200 for old_start, old_end in prior_segments
                    if (current_point == old_start and next_point == old_end)
                    or (current_point == old_end and next_point == old_start)
                )
                new_cost = cost + length + (70 if direction and direction != next_direction else 0) + overlap_penalty
                next_state = (nx, ny, next_direction)
                if new_cost < distances.get(next_state, inf):
                    distances[next_state] = new_cost
                    previous[next_state] = state
                    heappush(queue, (new_cost, next(serial), nx, ny, next_direction))
        if final_state is None:
            return None, inf
        path = []
        state = final_state
        while state != (start[0], start[1], 0):
            path.append((xs[state[0]], ys[state[1]]))
            state = previous[state]
        path.append(start_point)
        path.reverse()
        return path, distances[final_state]

    best = None
    for source_port, source_stub in source_ports:
        for target_port, target_stub in target_ports:
            path, cost = find_path(source_stub, target_stub)
            if path is None:
                continue
            total_cost = cost + abs(source_port[0] - source_stub[0]) + abs(source_port[1] - source_stub[1])
            total_cost += abs(target_port[0] - target_stub[0]) + abs(target_port[1] - target_stub[1])
            if best is None or total_cost < best[0]:
                best = (total_cost, [source_port, *path, target_port])
    if best is None:
        start = (source_rect[2], source_y + source_height // 2)
        end = (target_rect[0], target_y + target_height // 2)
        return [start, (end[0], start[1]), end]

    simplified = [best[1][0]]
    for point in best[1][1:]:
        if len(simplified) >= 2:
            a, b = simplified[-2], simplified[-1]
            if (a[0] == b[0] == point[0]) or (a[1] == b[1] == point[1]):
                simplified[-1] = point
                continue
        simplified.append(point)
    return simplified


def _relationship_label_point(route, at_start=None):
    if at_start is not None:
        start, end = (route[0], route[1]) if at_start else (route[-1], route[-2])
        dx = 0 if start[0] == end[0] else (1 if end[0] > start[0] else -1)
        dy = 0 if start[1] == end[1] else (1 if end[1] > start[1] else -1)
        return start[0] + dx * 18 - dy * 9, start[1] + dy * 18 + dx * 9
    segments = [
        (start, end, abs(end[0] - start[0]) + abs(end[1] - start[1]))
        for start, end in zip(route, route[1:])
    ]
    start, end, _ = max(segments, key=lambda segment: segment[2])
    return ((start[0] + end[0]) // 2, (start[1] + end[1]) // 2 - 10)


def generate_diagram_svg(db: Session, model_id: int, diagram_type: str = "uml") -> str:
    if diagram_type not in {"uml", "erd"}:
        raise ValueError("diagram_type must be 'uml' or 'erd'")
    classes = _classes_for_diagram(db, model_id, diagram_type)
    if not classes:
        return ""

    relationships = _relationships_for_diagram(db, model_id, {item.class_id for item in classes})
    if diagram_type == "erd":
        classes, relationships = _expand_erd_junctions(classes, relationships)

    classes_by_id = {uml_class.class_id: uml_class for uml_class in classes}
    rendered_members, positions, width, height = _diagram_layout(
        classes, diagram_type, classes_by_id, relationships
    )
    svg = Element(
        "svg",
        {
            "xmlns": "http://www.w3.org/2000/svg",
            "width": str(width),
            "height": str(height),
            "viewBox": f"0 0 {width} {height}",
        },
    )
    SubElement(svg, "rect", {"width": "100%", "height": "100%", "fill": "#ffffff"})
    definitions = SubElement(svg, "defs")
    inheritance_marker = SubElement(definitions, "marker", {
        "id": "uml-inheritance", "viewBox": "0 0 12 12", "refX": "10", "refY": "6",
        "markerWidth": "12", "markerHeight": "12", "orient": "auto",
    })
    SubElement(inheritance_marker, "path", {
        "d": "M 1 1 L 10 6 L 1 11 z", "fill": "#ffffff", "stroke": "#333333",
    })
    for marker_id, fill in (("uml-aggregation", "#ffffff"), ("uml-composition", "#333333")):
        marker = SubElement(definitions, "marker", {
            "id": marker_id, "viewBox": "0 0 14 12", "refX": "2", "refY": "6",
            "markerWidth": "14", "markerHeight": "12", "orient": "auto-start-reverse",
        })
        SubElement(marker, "path", {
            "d": "M 1 6 L 7 1 L 13 6 L 7 11 z", "fill": fill, "stroke": "#333333",
        })

    previous_routes = []
    for relationship in relationships:
        route = _route_relationship(
            relationship.source_class_id,
            relationship.target_class_id,
            positions,
            previous_routes,
        )
        previous_routes.append(route)
        relationship_type = (relationship.relationship_type or "").lower()
        marker_attributes = {}
        if diagram_type == "uml":
            if relationship_type == "inheritance":
                marker_attributes["marker-end"] = "url(#uml-inheritance)"
            elif relationship_type in {"aggregation", "composition"}:
                marker_attributes["marker-start"] = f"url(#uml-{relationship_type})"
        path = SubElement(svg, "path", {
            "d": " ".join(
                f"{'M' if index == 0 else 'L'} {point[0]} {point[1]}"
                for index, point in enumerate(route)
            ),
            "fill": "none",
            "stroke": "#333333",
            "stroke-width": "2",
            "data-relationship": str(relationship.relationship_id),
            "data-type": relationship.relationship_type or "Association",
            **marker_attributes,
        })

        if diagram_type == "erd" or relationship.multiplicity_source or relationship.multiplicity_target:
            for value, at_start, anchor in (
                (relationship.multiplicity_source or ("1" if diagram_type == "erd" else ""), True, "start"),
                (relationship.multiplicity_target or ("*" if diagram_type == "erd" else ""), False, "end"),
            ):
                if not value:
                    continue
                label_x, label_y = _relationship_label_point(route, at_start)
                endpoint_label = SubElement(svg, "text", {
                    "x": str(label_x), "y": str(label_y), "text-anchor": anchor,
                    "font-family": "Arial,sans-serif", "font-size": "13",
                    "font-weight": "bold", "fill": "#222222",
                    "stroke": "#ffffff", "stroke-width": "5", "paint-order": "stroke",
                    "stroke-linejoin": "round",
                })
                endpoint_label.text = value

        if diagram_type == "uml":
            relation_text = relationship.relationship_label or relationship.relationship_type or ""
            if relation_text:
                label_x, label_y = _relationship_label_point(route)
                relation_label = SubElement(svg, "text", {
                    "x": str(label_x), "y": str(label_y), "text-anchor": "middle",
                    "font-family": "Arial,sans-serif", "font-size": "13",
                    "fill": "#222222", "stroke": "#ffffff", "stroke-width": "5",
                    "paint-order": "stroke", "stroke-linejoin": "round",
                })
                relation_label.text = relation_text

    for uml_class in classes:
        x, y, box_width, box_height = positions[uml_class.class_id]
        cell_id = f"class-{uml_class.class_id}"
        shape = "table" if diagram_type == "erd" else "uml-class"
        SubElement(svg, "rect", {
            "x": str(x), "y": str(y), "width": str(box_width), "height": str(box_height),
            "fill": "#ffffff", "stroke": "#333333", "stroke-width": "2",
            "data-shape": shape, "data-id": cell_id,
        })
        title = SubElement(svg, "text", {
            "x": str(x + box_width // 2), "y": str(y + 30), "text-anchor": "middle",
            "font-family": "Arial,sans-serif", "font-size": "18", "font-weight": "bold",
        })
        title.text = uml_class.class_name or ""
        is_junction = diagram_type == "erd" and getattr(uml_class, "is_junction", False)
        if is_junction:
            junction_label = SubElement(svg, "text", {
                "x": str(x + box_width // 2), "y": str(y + 48), "text-anchor": "middle",
                "font-family": "Arial,sans-serif", "font-size": "12", "font-style": "italic",
            })
            junction_label.text = "<<Junction>>"
        divider_y = y + (56 if is_junction else 42)
        SubElement(svg, "line", {
            "x1": str(x), "y1": str(divider_y), "x2": str(x + box_width), "y2": str(divider_y),
            "stroke": "#333333",
        })
        member_data = rendered_members[uml_class.class_id]
        if diagram_type == "uml":
            attributes, methods = member_data
            rows_to_render = attributes + methods
            divider_at = y + 52 + len(attributes) * 20
            SubElement(svg, "line", {
                "x1": str(x), "y1": str(divider_at), "x2": str(x + box_width), "y2": str(divider_at),
                "stroke": "#a0a0a0",
            })
            start_y = y + 67
        else:
            rows_to_render = member_data
            start_y = y + (77 if is_junction else 65)
        for row, member in enumerate(rows_to_render):
            label = SubElement(svg, "text", {
                "x": str(x + 12), "y": str(start_y + row * 20),
                "font-family": "Arial,sans-serif", "font-size": "13",
            })
            label.text = member

    return tostring(svg, encoding="unicode", xml_declaration=True)
